import streamlit as st
import google.generativeai as genai
import sqlite3
import plotly.graph_objects as go
import json
from datetime import datetime, timedelta
import pandas as pd
import requests
import time
import streamlit.components.v1 as components
import os

# --- SECTION 1: Configuration & Constants ---
CHARACTERS = {
    "감정": "몽글이", "활동": "꼼지", "신체": "콩알이", "리듬": "깜빡이", "실행": "반짝이", "감사": "성냥"
}

EMOTIONS_MAIN = ["우울", "불안", "무기력함", "긴장감", "짜증", "분노", "자책", "공포"]
EMOTIONS_OTHER = ["기쁨", "슬픔", "두려움", "평온", "초조", "죄책감", "부끄러움", "외로움", "혼란", "절망감", "안도감", "만족감", "질투"]
PHYSICAL_REACTIONS = ["심장 빨라짐", "손에 땀이 남", "근육 긴장", "답답함", "떨림", "두통", "소화불량", "어지러움", "숨이 막힘", "눈물이 났다", "무기력하다", "한숨이 났다", "피로감", "모르겠다"]
ACTION_RECORDS = ["아무 반응 없음", "그 자리를 피했음", "화내며 대응", "조용히 참고 견딤", "울거나 감정 표현", "다른 사람에게 하소연", "AI와 대화함", "혼자만의 시간을 가짐", "술이나 음식으로 달램", "운동이나 활동으로 해소"]

TONE_DESCRIPTIONS = {
    1: "치유자 (따뜻한 수식어/감탄사 적극 사용)", 2: "상담사 (격식 있고 지지적인 언어)",
    3: "파트너 (따뜻함과 객관성의 중립)", 4: "전문가 (감정 배제, 명확한 전달)", 5: "분석기 (데이터와 팩트 위주)"
}
STYLE_DESCRIPTIONS = {
    1: "극강 F (감정 수용 최우선)", 2: "정서 우선 (정서적 지지)", 3: "심리 균형 (공감과 논리 반반)",
    4: "논리 우선 (인지 오류 식별)", 5: "극강 T (객관적 증거와 해결 중심)"
}
FOCUS_DESCRIPTIONS = {
    1: "심층 성찰 (내면 탐사)", 2: "의미 발견 (교훈 가이드)", 3: "통합 조언 (원인과 해결 절충)",
    4: "실천 중심 (행동 지침)", 5: "강력 솔루션 (로드맵 제시)"
}

# --- SECTION 2: Backend Logic ---
DB_FILE = "test_mind_diary.db"

def init_db():
    conn = sqlite3.connect(DB_FILE); c = conn.cursor()
    c.execute('CREATE TABLE IF NOT EXISTS logs (date TEXT PRIMARY KEY, diary_content TEXT, analysis_json TEXT)')
    conn.commit(); conn.close()

def get_log(date_str):
    conn = sqlite3.connect(DB_FILE); c = conn.cursor()
    c.execute("SELECT diary_content, analysis_json FROM logs WHERE date=?", (date_str,))
    res = c.fetchone(); conn.close()
    return res

def save_log(date_str, content, analysis_json):
    conn = sqlite3.connect(DB_FILE); c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO logs (date, diary_content, analysis_json) VALUES (?, ?, ?)", (date_str, content, analysis_json))
    conn.commit(); conn.close()

def delete_log(date_str):
    conn = sqlite3.connect(DB_FILE); c = conn.cursor()
    c.execute("DELETE FROM logs WHERE date=?", (date_str,))
    conn.commit(); conn.close()

def get_all_dates_with_logs():
    conn = sqlite3.connect(DB_FILE); c = conn.cursor()
    c.execute("SELECT date FROM logs"); rows = c.fetchall(); conn.close()
    return [r[0] for r in rows]

# --- SECTION 3: AI Logic ---
def analyze_diary(api_key, diary_text, tone_v, style_v, focus_v):
    if not api_key: return None
    # 로버스트한 API 키 클리닝 (실수로 GOOGLE_API_KEY = "..." 전체를 붙여넣은 경우 대비)
    api_key = api_key.strip()
    if "=" in api_key: api_key = api_key.split("=")[-1].strip()
    api_key = api_key.strip('"').strip("'").strip()
    
    t_ins = TONE_DESCRIPTIONS.get(tone_v); s_ins = STYLE_DESCRIPTIONS.get(style_v); f_ins = FOCUS_DESCRIPTIONS.get(focus_v)
    
    prompt = f"""
    당신은 몽글곰팅 님의 심리 코치입니다. 말투:{t_ins}, 성향:{s_ins}, 방향:{f_ins}.
    
    [JSON 출력 형식 필수]
    {{
        "mindfulness_board": [
            {{ "item": "감정", "character": "몽글이", "score": 1~5, "comment": "코멘트" }},
            ... (나머지: 활동-꼼지, 신체-콩알이, 리듬-깜빡이, 실행-반짝이, 감사-성냥)
        ],
        "gratitude_note": ["내용1", "내용2", "내용3"],
        "partner_comment": {{ "title": "제목", "content": "메시지" }},
        "cbt_analysis": {{
            "part1_main_emotions": ["주요감정"], "part1_sub_emotions": ["기타감정"], "part1_intensity": 0~100,
            "part2_situation": "상황", "part3_thought": "생각", "part4_physical": ["반응"],
            "part5_action": ["행동"], "part6_alternative": "대안",
            "emotion_ratio": {{ "negative": 0.0, "positive": 100.0 }}
        }}
    }}
    [규칙] 
    1. 모든 점수 최소 1점 보장. 
    2. 주요 감정은 {EMOTIONS_MAIN}에서, 기타 감정은 {EMOTIONS_OTHER}에서 선택. 
    3. 신체 반응/행동은 {PHYSICAL_REACTIONS}/{ACTION_RECORDS} 참고.
    """
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
    payload = {"contents": [{"parts": [{"text": f"{prompt}\n\n일기: {diary_text}"}]}], "generationConfig": {"temperature": 0.1}}
    try:
        resp = requests.post(url, json=payload)
        if resp.status_code == 200:
            raw = resp.json()['candidates'][0]['content']['parts'][0]['text']
            parsed = json.loads(raw.replace("```json", "").replace("```", "").strip())
            if "mindfulness_board" in parsed:
                for it in parsed["mindfulness_board"]:
                    if int(it.get("score", 1)) < 1: it["score"] = 1
            return parsed
        else:
            st.error(f"API 요청 실패 (Status: {resp.status_code}): {resp.text}")
            return None
    except Exception as e:
        st.error(f"AI 분석 파싱 중 오류 발생: {e}")
        return None
    return None

def generate_monthly_insight(api_key, text, t_v, s_v, f_v):
    if not api_key: return "API Key 필요"
    api_key = api_key.strip()
    if "=" in api_key: api_key = api_key.split("=")[-1].strip()
    api_key = api_key.strip('"').strip("'").strip()
    
    t_ins = TONE_DESCRIPTIONS.get(t_v); s_ins = STYLE_DESCRIPTIONS.get(s_v); f_ins = FOCUS_DESCRIPTIONS.get(f_v)
    prompt = f"심층 분석가로서 말투:{t_ins}, 성향:{s_ins}, 방향:{f_ins}을 반영해 보름/월간 리포트 작성.\n\n[데이터]\n{text}"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
    payload = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.1}}
    try:
        resp = requests.post(url, json=payload)
        return resp.json()['candidates'][0]['content']['parts'][0]['text'].strip() if resp.status_code == 200 else "실패"
    except: return "오류"

# --- SECTION 4: UI (Mobile Focused High-Fidelity) ---
st.set_page_config(layout="wide", page_title="마음챙김 & CBT TEST")
init_db()

st.markdown("""
    <style>
    textarea { height: auto !important; min-height: 100px !important; field-sizing: content !important; }
    [data-testid="stSidebar"] div.stSelectSlider { margin-bottom: 20px !important; }
    .stAlert { height: auto !important; }
    /* 모바일에서 컬럼 수직 쌓기 지지 */
    @media (max-width: 768px) {
        div[data-testid="stHorizontalBlock"] { flex-direction: column !important; }
    }
    </style>
""", unsafe_allow_html=True)

# Auto-grow JS
components.html("<script>function grow(){window.parent.document.querySelectorAll('textarea').forEach(t=>{t.style.height='auto';t.style.height=t.scrollHeight+'px'})}setInterval(grow,1000);grow();</script>", height=0)

with st.sidebar:
    st.title("⚙️ 클라우드 설정")
    api_key = st.text_input("Gemini API Key", type="password", value=st.secrets.get("GOOGLE_API_KEY", ""))
    st.divider()
    st.markdown("### 🎯 3축 정밀 설정")
    t_v = st.select_slider("말투(Tone)", options=[1,2,3,4,5], value=3, format_func=lambda x: ["치유자","상담사","파트너","전문가","분석기"][x-1])
    s_v = st.select_slider("성향(Style)", options=[1,2,3,4,5], value=3, format_func=lambda x: ["극강 F","정서 우선","균형","논리 우선","극강 T"][x-1])
    f_v = st.select_slider("방향(Focus)", options=[1,2,3,4,5], value=3, format_func=lambda x: ["성찰","의미","절충","실천","솔루션"][x-1])
    st.divider()
    with st.expander("📂 기록 목록", expanded=False):
        dates = sorted(get_all_dates_with_logs(), reverse=True)
        for d in dates:
            if st.button(f"📄 {d}", key=f"h_{d}"): st.session_state["sel_date"] = d; st.rerun()

st.title("🧠 마음챙김 & CBT 다이어리")
t1, t2 = st.tabs(["📝 오늘의 일기", "📊 리포트"])

with t1:
    if "sel_date" not in st.session_state: st.session_state["sel_date"] = datetime.now().strftime("%Y-%m-%d")
    date_str = st.session_state["sel_date"]
    saved = get_log(date_str)
    content = saved[0] if saved else ""
    try: data = json.loads(saved[1]) if saved and saved[1] else {}
    except: data = {}

    # Image 2 기반 3컬럼 구성
    col1, col2, col3 = st.columns([1.2, 1, 1.2])

    with col1:
        st.subheader("📝 오늘의 기록")
        st.caption(f"날짜: {date_str}")
        diary_in = st.text_area("오늘 어떤 일이 있었나요?", value=content, height=350, key=f"d_area_{date_str}")
        c_b1, c_b2 = st.columns(2)
        with c_b1:
            if st.button("🚀 AI 분석 및 저장", type="primary", use_container_width=True):
                if not api_key:
                    st.warning("⚠️ API Key가 없습니다. 사이드바나 Secrets를 확인해 주세요.")
                elif not diary_in:
                    st.warning("⚠️ 일기 내용을 입력해 주세요.")
                else:
                    with st.spinner("AI 분석 중 (약 5~10초)..."):
                        res = analyze_diary(api_key, diary_in, t_v, s_v, f_v)
                        if res:
                            save_log(date_str, diary_in, json.dumps(res, ensure_ascii=False))
                            st.success("✅ 분석 완료 및 저장되었습니다!"); time.sleep(1); st.rerun()
                        else:
                            st.error("❌ 분석에 실패했습니다. API 키나 서버 상태를 확인하세요.")
        with c_b2:
            if st.button("🗑️ 초기화(기록 삭제)", use_container_width=True): delete_log(date_str); st.rerun()

    board = data.get("mindfulness_board", [{"item": k, "character": v, "score": 1, "comment": "-"} for k, v in CHARACTERS.items()])
    cbt = data.get("cbt_analysis", {})
    if not isinstance(cbt, dict): cbt = {} # 방어적 코드
    
    with col2:
        st.subheader("📊 마음 챙김 보드")
        scores = {it['item']: it['score'] for it in board}
        cats = list(CHARACTERS.keys()); vals = [scores.get(c, 1) for c in cats]
        fig_r = go.Figure(data=go.Scatterpolar(r=vals + [vals[0]], theta=cats + [cats[0]], fill='toself'))
        fig_r.update_layout(polar=dict(radialaxis=dict(visible=True, range=[0, 5])), height=250, margin=dict(l=30,r=30,t=10,b=10))
        st.plotly_chart(fig_r, use_container_width=True)
        
        st.markdown("##### 📋 세부 분석 및 코멘트")
        df_b = pd.DataFrame(board)[["item", "character", "score", "comment"]].rename(columns={"item":"항목","character":"캐릭터","score":"점수","comment":"코멘트"})
        st.table(df_b)
        
        st.markdown("##### ⚖️ 감정 온도 (어제 vs 오늘)")
        prev_d = (datetime.strptime(date_str, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
        prev_log = get_log(prev_d)
        p_ratio = json.loads(prev_log[1]).get("cbt_analysis", {}).get("emotion_ratio", {"negative": 50, "positive": 50}) if prev_log else {"negative": 50, "positive": 50}
        c_ratio = cbt.get("emotion_ratio", {"negative": 50, "positive": 50})
        fig_b = go.Figure()
        fig_b.add_trace(go.Bar(y=["어제", "오늘"], x=[p_ratio.get("positive"), c_ratio.get("positive")], name="긍정", orientation='h', marker_color='#FF8C8C'))
        fig_b.add_trace(go.Bar(y=["어제", "오늘"], x=[p_ratio.get("negative"), c_ratio.get("negative")], name="부정", orientation='h', marker_color='#4FC3F7'))
        fig_b.update_layout(barmode='stack', height=180, margin=dict(l=10,r=10,t=10,b=10), showlegend=False)
        st.plotly_chart(fig_b, use_container_width=True)
        
        st.markdown("##### 🌷 오늘의 감사 노트")
        grats = data.get("gratitude_note", ["분석 후 생성됩니다.", "", ""])
        for i, g in enumerate(grats[:3]): st.text_area(f"감사 {i+1}", value=g, height=60, key=f"g_{i}_{date_str}", disabled=True)
        
        st.markdown("##### 🧠 마음 파트너의 한마디")
        # AttributeError 방지를 위한 safe get
        p_comment = data.get("partner_comment") if isinstance(data.get("partner_comment"), dict) else {}
        p_title = p_comment.get("title", "솔직한 용기")
        p_text = p_comment.get("content", "일기를 작성하고 분석하면 파트너가 응원을 보내드려요.")
        st.info(f"**[{p_title}]**\n\n{p_text}")

    with col3:
        st.subheader("💗 CBT 감정 노트")
        st.markdown("##### 💭 내면 탐색 (감정, 상황, 사고)")
        st.markdown("**Part 1. 감정 인식**")
        st.multiselect("주요 감정", EMOTIONS_MAIN, default=cbt.get("part1_main_emotions", []), disabled=True)
        st.multiselect("기타 감정", EMOTIONS_OTHER, default=cbt.get("part1_sub_emotions", []), disabled=True)
        st.slider("감정의 강도(%)", 0, 100, int(cbt.get("part1_intensity", 0)), disabled=True)
        
        st.markdown("**Part 2. 상황 파악**")
        st.text_area("객관적 사실", value=cbt.get("part2_situation", ""), height=100, disabled=True)
        
        st.markdown("**Part 3. 자동적 사고**")
        st.text_area("머친 생각이 들었나요?", value=cbt.get("part3_thought", ""), height=100, disabled=True)
        
        st.markdown("---")
        st.markdown("##### 🏃 행동 및 변화 (신체, 행동, 대안)")
        st.markdown("**Part 4. 신체 반응**")
        st.multiselect("신체 반응", PHYSICAL_REACTIONS, default=cbt.get("part4_physical", []), disabled=True)
        
        st.markdown("**Part 5. 행동 기록**")
        st.multiselect("행동 기록", ACTION_RECORDS, default=cbt.get("part5_action", []), disabled=True)
        
        st.markdown("**Part 6. 대안적 사고**")
        st.text_area("분석적/건조적 대안", value=cbt.get("part6_alternative", ""), height=150, disabled=True)
        
        if st.button("수정사항 저장", use_container_width=True): st.toast("테스트 환경에서는 AI 분석 결과가 자동으로 저장됩니다.")

with t2:
    st.header("📊 월간 리포트")
    c = sqlite3.connect(DB_FILE); df = pd.read_sql_query("SELECT * FROM logs", c); c.close()
    if df.empty: st.info("기록이 없습니다.")
    else:
        m = st.selectbox("분석 월", sorted(list(set(d[:7] for d in df['date'])), reverse=True))
        if st.button("✨ 심층 리포트 생성", type="primary", use_container_width=True):
            with st.spinner("생성 중..."):
                txt = "\n".join([f"[{r['date']}] {r['diary_content']}" for _, r in df[df['date'].str.startswith(m)].iterrows()])
                st.markdown(generate_monthly_insight(api_key, txt, t_v, s_v, f_v))
