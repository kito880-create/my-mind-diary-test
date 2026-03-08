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

def clean_api_key(key):
    if not key: return ""
    key = key.strip()
    # "KEY = VALUE" 형태일 때만 분리 (키 값 자체의 =와 구분)
    if "=" in key and any(word in key.upper() for word in ["API", "KEY", "GOOGLE"]):
        key = key.split("=")[-1].strip()
    return key.strip('"').strip("'").strip()

def get_prioritized_models(api_key):
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    try:
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            models = resp.json().get('models', [])
            candidates = [m.get('name', '').replace('models/', '') for m in models if 'generateContent' in m.get('supportedGenerationMethods', [])]
            if candidates:
                return sorted(candidates, key=lambda x: ('flash' not in x.lower(), 'pro' not in x.lower()))
    except: pass
    return ["gemini-1.5-flash", "gemini-1.5-flash-latest", "gemini-pro"]

# --- SECTION 3: AI Logic ---
def analyze_diary(api_key, diary_text, tone_v, style_v, focus_v):
    api_key = clean_api_key(api_key)
    if not api_key: return None
    
    t_ins = TONE_DESCRIPTIONS.get(tone_v); s_ins = STYLE_DESCRIPTIONS.get(style_v); f_ins = FOCUS_DESCRIPTIONS.get(focus_v)
    prompt = f"""당신은 몽글곰팅 님의 심리 코치입니다. 말투:{t_ins}, 성향:{style_v}, 방향:{focus_v}.
    [JSON 형식 필수] {{
        "mindfulness_board": [{"item":"감정","character":"몽글이","score":1~5,"comment":"..."}, ...],
        "gratitude_note": ["1","2","3"], "partner_comment": {{"title":"...","content":"..."}},
        "cbt_analysis": {{ "part1_main_emotions":["..."], "part1_sub_emotions":["..."], "part1_intensity":0~100, "part2_situation":"...", "part3_thought":"...", "part4_physical":["..."], "part5_action":["..."], "part6_alternative":"...", "emotion_ratio":{{"negative":0, "positive":100}} }}
    }}"""
    
    model_list = get_prioritized_models(api_key)
    errors = []
    for model in model_list[:5]: # 너무 많은 시도는 방지
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        payload = {"contents": [{"parts": [{"text": f"{prompt}\n\n일기: {diary_text}"}]}], "generationConfig": {"temperature": 0.1}}
        try:
            resp = requests.post(url, json=payload, timeout=15)
            if resp.status_code == 200:
                raw = resp.json()['candidates'][0]['content']['parts'][0]['text']
                parsed = json.loads(raw.replace("```json", "").replace("```", "").strip())
                # 데이터 보정
                if "mindfulness_board" in parsed:
                    for it in parsed["mindfulness_board"]: it["score"] = max(1, int(it.get("score", 1)))
                return parsed
            errors.append(f"{model}: {resp.status_code}")
        except Exception as e:
            errors.append(f"{model}: {str(e)[:50]}")
    
    st.error(f"❌ 분석 실패. 시도된 모델: {', '.join(errors[:3])}")
    return None

def generate_monthly_insight(api_key, text, t_v, s_v, f_v):
    api_key = clean_api_key(api_key)
    if not api_key: return "API Key 필요"
    t_ins = TONE_DESCRIPTIONS.get(t_v); s_ins = STYLE_DESCRIPTIONS.get(s_v); f_ins = FOCUS_DESCRIPTIONS.get(f_v)
    prompt = f"심층 분석가로서 말투:{t_ins}, 성향:{s_ins}, 방향:{f_ins}을 반영해 보름/월간 리포트 작성.\n\n[데이터]\n{text}"
    model_list = get_prioritized_models(api_key)
    for model in model_list[:3]:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        payload = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.1}}
        try:
            resp = requests.post(url, json=payload, timeout=30)
            if resp.status_code == 200: return resp.json()['candidates'][0]['content']['parts'][0]['text'].strip()
        except: continue
    return "분석 실패 (AI 모델 응답 없음)"

# --- SECTION 4: UI ---
st.set_page_config(layout="wide", page_title="마음챙김 & CBT TEST", initial_sidebar_state="expanded")
init_db()

st.markdown("""
    <style>
    textarea { height: auto !important; min-height: 100px !important; field-sizing: content !important; }
    @media (max-width: 768px) { div[data-testid="stHorizontalBlock"] { flex-direction: column !important; } }
    </style>
""", unsafe_allow_html=True)
components.html("<script>function grow(){window.parent.document.querySelectorAll('textarea').forEach(t=>{t.style.height='auto';t.style.height=t.scrollHeight+'px'})}setInterval(grow,1000);</script>", height=0)

with st.sidebar:
    st.title("⚙️ 설정")
    api_key = st.text_input("Gemini API Key", type="password", value=st.secrets.get("GOOGLE_API_KEY", ""))
    st.divider()
    t_v = st.select_slider("말투(Tone)", options=[1,2,3,4,5], value=3, format_func=lambda x: ["치유자","상담사","파트너","전문가","분석기"][x-1])
    s_v = st.select_slider("성향(Style)", options=[1,2,3,4,5], value=3, format_func=lambda x: ["극강 F","정서 우선","균형","논리 우선","극강 T"][x-1])
    f_v = st.select_slider("방향(Focus)", options=[1,2,3,4,5], value=3, format_func=lambda x: ["성찰","의미","절충","실천","솔루션"][x-1])
    st.divider()
    with st.expander("📂 기록 목록"):
        for d in sorted(get_all_dates_with_logs(), reverse=True):
            if st.button(f"📄 {d}", key=f"h_{d}"): st.session_state["sel_date"] = d; st.rerun()

st.title("🧠 마음챙김 & CBT 다이어리")
t1, t2 = st.tabs(["📝 오늘의 일기", "📊 리포트"])

with t1:
    if "sel_date" not in st.session_state: st.session_state["sel_date"] = datetime.now().strftime("%Y-%m-%d")
    date_str = st.session_state["sel_date"]
    saved = get_log(date_str)
    diary_in = st.text_area("오늘 어떤 일이 있었나요?", value=saved[0] if saved else "", height=350, key=f"d_area_{date_str}")
    
    c1, c2 = st.columns(2)
    with c1:
        if st.button("🚀 AI 분석 및 저장", type="primary", use_container_width=True):
            if not api_key or not diary_in: st.warning("내용과 API 키를 확인해 주세요.")
            else:
                with st.spinner("분석 중..."):
                    res = analyze_diary(api_key, diary_in, t_v, s_v, f_v)
                    if res: save_log(date_str, diary_in, json.dumps(res, ensure_ascii=False)); st.success("성공!"); time.sleep(0.5); st.rerun()
    with c2:
        if st.button("🗑️ 초기화", use_container_width=True): delete_log(date_str); st.rerun()

    data = json.loads(saved[1]) if saved and saved[1] else {}
    col1, col2, col3 = st.columns([1, 1, 1])
    
    with col1:
        st.subheader("📊 마음 챙김 보드")
        board = data.get("mindfulness_board", [{"item":k,"character":v,"score":1,"comment":"-"} for k,v in CHARACTERS.items()])
        vals = [int(it.get("score", 1)) for it in board]
        fig = go.Figure(data=go.Scatterpolar(r=vals+[vals[0]], theta=list(CHARACTERS.keys())+[list(CHARACTERS.keys())[0]], fill='toself'))
        fig.update_layout(polar=dict(radialaxis=dict(visible=True, range=[0,5])), height=250, margin=dict(l=20,r=20,t=20,b=20))
        st.plotly_chart(fig, use_container_width=True)
        st.table(pd.DataFrame(board)[["item","character","score","comment"]].rename(columns={"item":"항목","character":"캐릭터","score":"점수","comment":"코멘트"}))

    with col2:
        st.subheader("⚖️ 감정 온도")
        cbt = data.get("cbt_analysis", {})
        ratio = cbt.get("emotion_ratio", {"negative":50, "positive":50})
        fig2 = go.Figure(go.Bar(x=[ratio.get("positive"), ratio.get("negative")], y=["상태"], orientation='h', marker_color=['#FF8C8C','#4FC3F7']))
        fig2.update_layout(barmode='stack', height=150, margin=dict(l=10,r=10,t=10,b=10), showlegend=False)
        st.plotly_chart(fig2, use_container_width=True)
        
        st.markdown("##### 🌷 감사 노트")
        for i, g in enumerate(data.get("gratitude_note", ["-","-","-"])[:3]): 
            st.info(f"{i+1}. {g}")
            
        st.info(f"**[{data.get('partner_comment',{}).get('title','마음 파트너')}]**\n\n{data.get('partner_comment',{}).get('content','이야기를 들려주세요.')}")

    with col3:
        st.subheader("💗 CBT 감정 노트")
        st.caption("Part 1. 감정 인식")
        st.write(f"주요: {', '.join(cbt.get('part1_main_emotions', []))}")
        st.write(f"강도: {cbt.get('part1_intensity', 0)}%")
        st.caption("Part 2. 상황 파악")
        st.info(cbt.get("part2_situation", "-"))
        st.caption("Part 3. 자동적 사고")
        st.info(cbt.get("part3_thought", "-"))
        st.caption("Part 6. 대안적 사고")
        st.success(cbt.get("part6_alternative", "-"))

with t2:
    st.header("📊 리포트")
    c = sqlite3.connect(DB_FILE); df = pd.read_sql_query("SELECT * FROM logs", c); c.close()
    if not df.empty:
        m = st.selectbox("월 선택", sorted(list(set(d[:7] for d in df['date'])), reverse=True))
        if st.button("✨ 리포트 생성", type="primary"):
            txt = "\n".join([r['diary_content'] for _, r in df[df['date'].str.startswith(m)].iterrows()])
            st.write(generate_monthly_insight(api_key, txt, t_v, s_v, f_v))
