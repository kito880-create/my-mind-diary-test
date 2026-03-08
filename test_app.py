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
import shutil
import os

# --- SECTION 1: Configuration & Constants ---

# 1. 감정 캐릭터 및 항목
CHARACTERS = {
    "감정": "몽글이", "활동": "꼼지", "신체": "콩알이", "리듬": "깜빡이", "실행": "반짝이", "감사": "성냥"
}

# 2. 감정 선택지
EMOTIONS_MAIN = ["우울", "불안", "무기력함", "긴장감", "짜증", "분노", "자책", "공포"]
EMOTIONS_OTHER = ["기쁨", "슬픔", "두려움", "평온", "초조", "죄책감", "부끄러움", "외로움", "혼란", "절망감", "안도감", "만족감", "질투"]
ALL_EMOTIONS = EMOTIONS_MAIN + EMOTIONS_OTHER

# 3. 부정 감정 키워드
neg_keywords = ["우울", "불안", "무기력함", "짜증", "분노", "자책", "공포", "슬픔", "두려움", "절망감"]

# 4. 신체 반응 및 행동 기록
PHYSICAL_REACTIONS = ["심장 빨라짐", "손에 땀이 남", "근육 긴장", "답답함", "떨림", "두통", "소화불량", "어지러움", "숨이 막힘", "눈물이 났다", "무기력하다", "한숨이 났다", "피로감", "모르겠다"]
ACTION_RECORDS = ["아무 반응 없음", "그 자리를 피했음", "화내며 대응", "조용히 참고 견딤", "울거나 감정 표현", "다른 사람에게 하소연", "AI와 대화함", "혼자만의 시간을 가짐", "술이나 음식으로 달램", "운동이나 활동으로 해소"]

# 5. 3대 분석 축 정의 데이터
TONE_DESCRIPTIONS = {
    1: "포근한 치유자 (따뜻한 수식어/감탄사 적극 사용)",
    2: "부드러운 상담사 (격식 있고 지지적인 언어)",
    3: "균형 잡힌 파트너 (따뜻함과 객관성의 중립)",
    4: "담백한 전문가 (감정 배제, 명확한 전달)",
    5: "건조한 분석기 (데이터와 팩트 위주)"
}

STYLE_DESCRIPTIONS = {
    1: "극강 F (감정의 결, 주관적 가치 최우선)",
    2: "정서 우선 (마음의 흐름과 수용 중심)",
    3: "심리 균형 (공감 50%, 논리 50%)",
    4: "논리 우선 (객관적 사실과 인지 오류 식별)",
    5: "극강 T (인과관계, 증거, 효율성 중심)"
}

FOCUS_DESCRIPTIONS = {
    1: "심층 성찰 (내면의 의미와 통찰 질문)",
    2: "의미 발견 (삶의 가치와 교훈 가이드)",
    3: "통합 조언 (원인 분석 50%, 실천 제안 50%)",
    4: "실천 중심 (기분 전환 및 문제 해결 팁)",
    5: "강력 솔루션 (단계별 로드맵 및 To-Do List)"
}

# --- SECTION 2: Backend Logic ---
DB_FILE = "test_mind_diary.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS logs
                 (date TEXT PRIMARY KEY, diary_content TEXT, analysis_json TEXT)''')
    conn.commit()
    conn.close()

def normalize_date_str(date_str):
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return dt.strftime("%Y-%m-%d"), date_str
    except:
        return date_str, date_str

def get_log(date_str):
    conn = sqlite3.connect(DB_FILE); c = conn.cursor()
    std, _ = normalize_date_str(date_str)
    c.execute("SELECT diary_content, analysis_json FROM logs WHERE date=?", (std,))
    res = c.fetchone(); conn.close()
    return res

def save_log(date_str, content, analysis_json):
    conn = sqlite3.connect(DB_FILE); c = conn.cursor()
    std, _ = normalize_date_str(date_str)
    c.execute("INSERT OR REPLACE INTO logs (date, diary_content, analysis_json) VALUES (?, ?, ?)", (std, content, analysis_json))
    conn.commit(); conn.close()

def delete_log(date_str):
    conn = sqlite3.connect(DB_FILE); c = conn.cursor()
    std, _ = normalize_date_str(date_str)
    c.execute("DELETE FROM logs WHERE date=?", (std,))
    conn.commit(); conn.close()

def get_all_dates_with_logs():
    conn = sqlite3.connect(DB_FILE); c = conn.cursor()
    c.execute("SELECT date FROM logs")
    rows = c.fetchall(); conn.close()
    return [r[0] for r in rows]

# --- SECTION 3: Gemini API Logic ---
def get_prioritized_models(api_key):
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    try:
        resp = requests.get(url)
        if resp.status_code != 200: return []
        models = resp.json().get('models', [])
        candidates = [m.get('name', '').replace('models/', '') for m in models if 'generateContent' in m.get('supportedGenerationMethods', [])]
        return sorted(candidates, key=lambda x: ('flash' not in x.lower(), 'pro' not in x.lower()))
    except: return []

def analyze_diary(api_key, diary_text, tone_val, style_val, focus_val):
    if not api_key: return None
    model_list = get_prioritized_models(api_key) or ["gemini-1.5-flash"]
    
    tone_ins = TONE_DESCRIPTIONS.get(tone_val)
    style_ins = STYLE_DESCRIPTIONS.get(style_val)
    focus_ins = FOCUS_DESCRIPTIONS.get(focus_val)
    
    system_instruction = f"""
    당신은 사용자의 일기를 분석하는 전문 심리 코치 '마음 파트너'입니다.
    사용자 이름은 '몽글곰팅 님'입니다.
    
    [분석 필터링 설정]
    1. 말투: {tone_ins}
    2. 성향: {style_ins}
    3. 방향: {focus_ins}
    
    [출력 규칙]
    - 모든 점수는 최소 1점 이상 보장.
    - JSON 형식을 엄수할 것. (mindfulness_board, gratitude_note, partner_comment, cbt_analysis 포함)
    """
    
    prompt = f"{system_instruction}\n\n[사용자 일기]\n{diary_text}"
    for model in model_list:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        payload = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.1}}
        try:
            resp = requests.post(url, json=payload)
            if resp.status_code == 200:
                text = resp.json()['candidates'][0]['content']['parts'][0]['text']
                text = text.replace("```json", "").replace("```", "").strip()
                parsed = json.loads(text)
                if "mindfulness_board" in parsed:
                    for item in parsed["mindfulness_board"]:
                        if item.get("score", 1) < 1: item["score"] = 1
                return parsed
        except: continue
    return None

def generate_monthly_insight(api_key, month_text, tone_val, style_val, focus_val):
    if not api_key: return "API Key가 없습니다."
    
    tone_ins = TONE_DESCRIPTIONS.get(tone_val)
    style_ins = STYLE_DESCRIPTIONS.get(style_val)
    focus_ins = FOCUS_DESCRIPTIONS.get(focus_val)
    
    prompt = f"당신은 분석가입니다. 말투:{tone_ins}, 성향:{style_ins}, 방향:{focus_ins}에 맞춰 월간 리포트를 작성하세요.\n\n[데이터]\n{month_text}"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
    payload = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.1}}
    try:
        resp = requests.post(url, json=payload)
        if resp.status_code == 200:
            return resp.json()['candidates'][0]['content']['parts'][0]['text'].strip()
    except: pass
    return "분석 실패."

# --- SECTION 4: UI Layout (Mobile Optimized) ---
st.set_page_config(layout="wide", page_title="[Mobile/Cloud] 마음챙김 TEST")
init_db()

# 모바일 대응 CSS
st.markdown("""
    <style>
    /* 모바일에서 텍스트 영역 자동 높이 조절 */
    textarea {
        height: auto !important;
        min-height: 150px !important; /* 모바일 터치 편의성 */
        field-sizing: content !important;
    }
    /* 사이드바 슬라이더 간격 조절 */
    [data-testid="stSidebar"] div.stSelectSlider {
        margin-bottom: 25px !important;
    }
    /* 모바일에서 컬럼 가독성 강화 */
    @media (max-width: 768px) {
        div[data-testid="stHorizontalBlock"] {
            flex-direction: column !important;
        }
    }
    </style>
""", unsafe_allow_html=True)

with st.sidebar:
    st.title("⚙️ 클라우드 설정")
    # API 키 보안 관리 (Secrets 우선 적용)
    default_key = st.secrets.get("GOOGLE_API_KEY", "")
    api_key = st.text_input("Gemini API Key", type="password", value=default_key)
    
    if not api_key:
        st.warning("⚠️ 클라우드 배포 시 'Secrets'에 API 키를 등록하거나 위 창에 입력해 주세요.")
    
    st.divider()
    st.markdown("### 🎯 3축 정밀 분석 설정")
    tone_val = st.select_slider("말투(Tone)", options=[1, 2, 3, 4, 5], value=3, 
                                format_func=lambda x: ["치유자", "상담사", "파트너", "전문가", "분석기"][x-1])
    style_val = st.select_slider("성향(Style)", options=[1, 2, 3, 4, 5], value=3,
                                 format_func=lambda x: ["극강 F", "정서 우선", "균형", "논리 우선", "극강 T"][x-1])
    focus_val = st.select_slider("방향(Focus)", options=[1, 2, 3, 4, 5], value=3,
                                 format_func=lambda x: ["성찰", "의견", "절충", "실천", "솔루션"][x-1])
    
    st.divider()
    with st.expander("📂 기록 목록", expanded=False):
        dates = get_all_dates_with_logs()
        dates.sort(reverse=True)
        for d in dates:
            if st.button(f"📄 {d}", key=f"h_{d}"):
                st.session_state["selected_date_str"] = d; st.rerun()

st.title("🧠 마음챙김 & CBT 다이어리")
tab1, tab2 = st.tabs(["📝 오늘의 일기", "📊 리포트"])

with tab1:
    if "selected_date_str" not in st.session_state:
        st.session_state["selected_date_str"] = datetime.now().strftime("%Y-%m-%d")
    
    date_str = st.session_state["selected_date_str"]
    saved = get_log(date_str)
    content = saved[0] if saved else ""
    data = json.loads(saved[1]) if saved else {}

    # 모바일에서는 순차적으로 표시됨
    col1, col2, col3 = st.columns([1.2, 1, 1])
    
    with col1:
        st.subheader("📝 오늘의 일기")
        diary_in = st.text_area("오늘 어떤 일이 있었나요?", value=content, height=250)
        c1, c2 = st.columns(2)
        with c1:
            if st.button("🚀 분석/저장", use_container_width=True, type="primary"):
                if api_key and diary_in:
                    with st.spinner("AI 분석 중..."):
                        res = analyze_diary(api_key, diary_in, tone_val, style_val, focus_val)
                        if res:
                            save_log(date_str, diary_in, json.dumps(res, ensure_ascii=False))
                            st.success("완료!"); st.rerun()
        with c2:
            if st.button("🗑️ 초기화", use_container_width=True): delete_log(date_str); st.rerun()

    board = data.get("mindfulness_board", [{"item": k, "score": 1, "comment": "-"} for k in CHARACTERS.keys()])
    cbt = data.get("cbt_analysis", {"part1_intensity": 50, "emotion_ratio": {"negative":50, "positive":50}})
    
    with col2:
        st.subheader("📊 분석 보드")
        vals = [next((it['score'] for it in board if it.get('item') == k), 1) for k in CHARACTERS.keys()]
        fig = go.Figure(data=go.Scatterpolar(r=vals + [vals[0]], theta=list(CHARACTERS.keys()) + [list(CHARACTERS.keys())[0]], fill='toself'))
        fig.update_layout(polar=dict(radialaxis=dict(visible=True, range=[0, 5])), height=250, margin=dict(l=40, r=40, t=20, b=20))
        st.plotly_chart(fig, use_container_width=True)
        
        st.markdown("#### 🌷 감사 노트")
        grats = data.get("gratitude_note", ["", "", ""])
        for i, g in enumerate(grats[:3]):
            st.info(f"{i+1}. {g}")

    with col3:
        st.subheader("❤️ CBT 요약")
        st.progress(cbt.get("part1_intensity", 50)/100, text=f"감정 강도: {cbt.get('part1_intensity', 0)}%")
        st.info(f"**[파트너의 한마디]**\n\n{data.get('partner_comment', {}).get('content', '일기를 작성해 주세요.')}")

with tab2:
    st.header("📊 월간 분석")
    conn = sqlite3.connect(DB_FILE); df = pd.read_sql_query("SELECT * FROM logs", conn); conn.close()
    if df.empty: st.info("데이터가 없습니다.")
    else:
        month = st.selectbox("분석할 월", sorted(list(set(d[:7] for d in df['date'])), reverse=True))
        if st.button("✨ 리포트 생성", type="primary", use_container_width=True):
            target_text = "\n".join([f"[{r['date']}] {r['diary_content']}" for _, r in df[df['date'].str.startswith(month)].iterrows()])
            with st.spinner("심층 리포트 생성 중..."):
                report = generate_monthly_insight(api_key, target_text, tone_val, style_val, focus_val)
                st.markdown(report)
