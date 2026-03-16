import streamlit as st
import re, requests, json, time, random, os, base64, sys

# --- 核心導入 ---
try:
    from moviepy import ImageClip, AudioFileClip, concatenate_videoclips, CompositeVideoClip
except:
    from moviepy.editor import ImageClip, AudioFileClip, concatenate_videoclips, CompositeVideoClip

# --- 1. 配置與權限 ---
st.set_page_config(page_title="MV Visual Director (Budget Manager)", layout="wide")

# 從後台讀取金鑰
API_KEY = st.secrets.get("OPENAI_API_KEY", "")

IMG_DIR = "generated_frames"
if not os.path.exists(IMG_DIR): os.makedirs(IMG_DIR)

# 初始化狀態
if "global_v" not in st.session_state: st.session_state.global_v = 0
if "row_versions" not in st.session_state: st.session_state.row_versions = {}

# --- 2. 側邊欄：模型與預算控制台 ---
with st.sidebar:
    st.header("🔑 導演認證")
    director_pw = st.text_input("輸入導演通行碼", type="password")
    if director_pw != st.secrets.get("DIRECTOR_PASSWORD", "mv888"):
        st.warning("請輸入正確密碼以解鎖")
        st.stop()

    st.success("認證成功！")
    st.divider()

    # --- 🤖 模型與預算配置 ---
    st.header("🤖 模型與預算配置")
    
    st.info("📜 **編劇：gpt-4o-mini**")
    st.caption("💰 價格：極便宜 (NT$ 0.01 可寫好幾首歌)")
    
    image_model = st.selectbox(
        "🎨 選擇產圖畫師",
        ["DALL-E 3 (精美/影視感)", "DALL-E 2 (便宜/意境感)"],
        index=0
    )
    
    # 動態預算計算
    if "DALL-E 3" in image_model:
        selected_model = "dall-e-3"
        cost_usd, cost_twd = 0.04, 1.3
        quality_desc = "高清、16:9 滿版、古風細節強"
        img_size = "1024x1792" 
    else:
        selected_model = "dall-e-2"
        cost_usd, cost_twd = 0.02, 0.6
        quality_desc = "普通、1:1 正方形、適合找靈感"
        img_size = "1024x1024"

    st.warning(f"""
    **💸 產圖預算提醒 (每張)：**
    - 美金：${cost_usd} USD
    - 台幣：約 **${cost_twd}** TWD
    - 特色：{quality_desc}
    """)
    st.divider()

    st.header("🎵 素材導入")
    lrc_file = st.file_uploader("1. 上傳 LRC", type=["lrc"])
    mp3_file = st.file_uploader("2. 上傳 MP3", type=["mp3"])
    
    style_category = st.selectbox("Style", ["Gufeng_Real", "Lo-fi", "Neon", "Film"])
    style_map = {
        "Gufeng_Real": "Cinematic photorealistic Gufeng, 8k, traditional Chinese architecture, silk textures, golden hour sunlight.",
        "Lo-fi": "Chill Lo-fi aesthetic, muted colors, cozy bedroom, grainy nostalgic vibe.",
        "Neon": "Neon Cyberpunk, magenta and cyan glow, wet street reflections.",
        "Film": "Cinematic 35mm film, professional color grading, anamorphic flares."
    }

    if st.button("🚀 啟動批量產圖"): st.session_state.is_running_batch = True
    if st.button("🎬 合成 MV"): st.session_state.trigger_video_export = True
    if st.button("🗑️ 清除所有暫存"):
        st.session_state.clear()
        import shutil
        if os.path.exists(IMG_DIR): shutil.rmtree(IMG_DIR)
        os.makedirs(IMG_DIR); st.rerun()

# --- 3. 核心函數 ---

def get_mini_ai_prompt(style_label, style_cmd, lyric):
    """【省錢編劇】"""
    url = "https://api.openai.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {API_KEY}"}
    prompt_msg = f"Visual Director: Describe a cinematic image for lyric '{lyric}' with style '{style_label}'. Keywords: {style_cmd}. English only, NO TEXT, NO PEOPLE."
    payload = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": prompt_msg}],
        "max_tokens": 150
    }
    try:
        res = requests.post(url, headers=headers, json=payload, timeout=10)
        return res.json()['choices'][0]['message']['content'].strip()
    except: return f"A stunning {style_label} scene"

def call_image_api(prompt):
    """【畫師】依據側邊欄選取的模型產圖"""
    url = "https://api.openai.com/v1/images/generations"
    headers = {"Authorization": f"Bearer {API_KEY}"}
    payload = {"model": selected_model, "prompt": prompt, "n": 1, "size": img_size}
    try:
        res = requests.post(url, headers=headers, json=payload, timeout=60)
        rj = res.json()
        if res.status_code == 200:
            img_url = rj['data'][0]['url']
            return base64.b64encode(requests.get(img_url).content).decode('utf-8')
    except: pass
    return None

def parse_perfect_logic(lrc_content, audio_duration):
    # (此處保留妳原本強大的 LRC 解析邏輯)
    raw_lines = lrc_content.split('\n')
    parsed_lines = []
    for line in raw_lines:
        if not line.strip() or not re.search(r"\[\d{2}:", line): continue
        match = re.search(r"\[(\d{2}):(\d{2}\.\d{2})\]", line)
        if match:
            m, s = match.groups()
            sec = int(m)*60 + float(s)
            txt = re.sub(r"\[.*?\]", "", line).strip()
            parsed_lines.append({"seconds": sec, "lyric": txt, "ts": f"{m}:{s}"})
    return parsed_lines

# --- 4. 介面渲染與執行 ---
if lrc_file and mp3_file:
    if "audio_dur" not in st.session_state:
        with open("active_temp.mp3", "wb") as f: f.write(mp3_file.getvalue())
        st.session_state.audio_dur = AudioFileClip("active_temp.mp3").duration
    
    timeline = parse_perfect_logic(lrc_file.getvalue().decode("utf-8", errors="ignore"), st.session_state.audio_dur)
    
    # 批量產圖
    if st.session_state.get("is_running_batch", False):
        diag = st.empty()
        for i, item in enumerate(timeline):
            imk = f"img_{i}"
            if imk not in st.session_state:
                pk = f"p_{i}"
                if pk not in st.session_state: 
                    st.session_state[pk] = get_mini_ai_prompt(style_category, style_map[style_category], item['lyric'])
                diag.warning(f"正在產圖 ({i+1}/{len(timeline)})")
                res = call_image_api(st.session_state[pk])
                if res:
                    with open(f"{IMG_DIR}/f_{i}.png", "wb") as f: f.write(base64.b64decode(res))
                    st.session_state[imk] = res
        st.session_state.is_running_batch = False; st.rerun()

    # 渲染列表
    for i, item in enumerate(timeline):
        c1, c2, c3, c4 = st.columns([1.5, 4, 4, 1.8])
        c1.markdown(f"**{item['ts']}**\n\n{item['lyric']}")
        pk, imk = f"p_{i}", f"img_{i}"
        
        if pk not in st.session_state: 
            st.session_state[pk] = "點擊「換劇本」生成分鏡..."
            
        st.session_state[pk] = c2.text_area("", st.session_state[pk], key=f"t_{i}", height=120, label_visibility="collapsed")
        
        if imk in st.session_state:
            c3.markdown(f'<img src="data:image/png;base64,{st.session_state[imk]}" style="width:100%; border-radius:8px;">', unsafe_allow_html=True)
        
        col_a, col_b = c4.columns(2)
        if col_a.button("🔄 換劇本", key=f"ref_{i}"):
            st.session_state[pk] = get_mini_ai_prompt(style_category, style_map[style_category], item['lyric'])
            st.rerun()
        if col_b.button("🎨 產圖", key=f"btn_{i}"):
            res = call_image_api(st.session_state[pk])
            if res: st.session_state[imk] = res; st.rerun()
        st.divider()
