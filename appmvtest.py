import streamlit as st
import re, requests, json, time, random, os, base64, sys

# --- 核心導入 ---
try:
    from moviepy import ImageClip, AudioFileClip, concatenate_videoclips, CompositeVideoClip
except:
    from moviepy.editor import ImageClip, AudioFileClip, concatenate_videoclips, CompositeVideoClip

# --- 1. 配置與安全 ---
st.set_page_config(page_title="MV Visual Director 24.5 (Secure)", layout="wide")

# 【安全修正】從 Streamlit Secrets 讀取，不准寫在程式碼裡
if "OPENAI_API_KEY" in st.secrets:
    API_KEY = st.secrets["OPENAI_API_KEY"]
else:
    st.error("❌ 請在 Streamlit Secrets 設置 OPENAI_API_KEY")
    st.stop()

IMG_DIR = "generated_frames"
if not os.path.exists(IMG_DIR): os.makedirs(IMG_DIR)

if "global_v" not in st.session_state: st.session_state.global_v = 0
if "row_versions" not in st.session_state: st.session_state.row_versions = {}

# --- 2. 側邊欄：模型與素材 ---
with st.sidebar:
    st.header("🤖 模型配置與預算")
    
    # 讓妳選產圖畫師
    image_model_choice = st.selectbox(
        "🎨 選擇產圖畫師",
        ["DALL-E 3 (精美/16:9)", "DALL-E 2 (便宜/1:1)"],
        index=0
    )
    
    if "DALL-E 3" in image_model_choice:
        selected_model, cost_twd, img_size = "dall-e-3", 1.3, "1024x1792"
    else:
        selected_model, cost_twd, img_size = "dall-e-2", 0.6, "1024x1024"

    st.warning(f"**💰 預估成本：** 每張約 NT$ {cost_twd}")
    st.divider()

    st.header("🎵 素材導入")
    lrc_file = st.file_uploader("1. 上傳 LRC", type=["lrc"])
    mp3_file = st.file_uploader("2. 上傳 MP3", type=["mp3"])
    
    style_category = st.selectbox("Style", ["Gufeng", "R&B", "Lo-fi", "KTV", "Neon", "Film"])
    
    style_map = {
        "Gufeng": "Cinematic photorealistic Gufeng, 8k, traditional Chinese architecture, silk textures, golden hour sunlight, 16:9.",
        "R&B": "R&B soul vibe, purple and gold lighting.",
        "Lo-fi": "Chill Lo-fi aesthetic, muted colors, cozy bedroom.",
        "KTV": "Classic KTV 90s style, VHS blurry texture.",
        "Neon": "Neon Cyberpunk, magenta and cyan glow.",
        "Film": "Cinematic 35mm film, professional color grading."
    }
    
    if st.button("♻️ 依照新風格重寫全場劇本"):
        st.session_state.global_v += 1
        st.session_state.row_versions = {}
        for key in list(st.session_state.keys()):
            if key.startswith("p_"): del st.session_state[key]
        st.rerun()

    if st.button("🚀 啟動批量產圖"): st.session_state.is_running_batch = True
    if st.button("🎬 合成滿版 16:9 MV"): st.session_state.trigger_video_export = True
    if st.button("🗑️ 清除所有暫存"):
        st.session_state.clear()
        import shutil
        if os.path.exists(IMG_DIR): shutil.rmtree(IMG_DIR)
        os.makedirs(IMG_DIR); st.rerun()

# --- 3. 核心函數 ---

def get_dynamic_prompt(style_label, style_cmd, tag, seed_val):
    random.seed(seed_val + st.session_state.global_v + time.time())
    prefixes = ["A stunning", "A majestic", "A vibrant", "A breathtaking", "A sharp"]
    angles = ["cinematic wide shot", "macro close-up", "low angle view", "wide-angle lens shot"]
    elements = ["scenery", "texture", "horizon"]
    
    if "Gufeng" in style_label:
        elements = ["ornate crimson palace walls", "ancient red wooden pavilion", "vibrant silk lanterns", "carved stone bridge", "blooming plum blossoms"]
    
    lighting = ["intense golden hour glow", "vivid amber sunlight", "high contrast shadows"]
    random.shuffle(prefixes); random.shuffle(angles)
    base = f"[{style_label}] {random.choice(prefixes)} {random.choice(angles)}"
    return f"{base} of {random.choice(elements)}, {style_cmd}, {random.choice(lighting)}, 8k, photorealistic, 16:9. NO PEOPLE, NO TEXT."
    
def call_openai_api(prompt, diag):
    url = "https://api.openai.com/v1/images/generations"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {API_KEY}"}
    payload = {"model": selected_model, "prompt": str(prompt), "n": 1, "size": img_size}
    try:
        res = requests.post(url, headers=headers, json=payload, timeout=60)
        rj = res.json()
        if res.status_code == 200:
            img_url = rj['data'][0]['url']
            return base64.b64encode(requests.get(img_url).content).decode('utf-8')
    except: pass
    return None

def parse_perfect_logic(lrc_content, audio_duration):
    """【完整保留】10秒補位邏輯，並洗淨歌詞雜質"""
    raw_lines = lrc_content.split('\n')
    parsed_lines = []
    c_idx = 0
    for line in raw_lines:
        if line.startswith('{') or not line.strip() or not re.search(r"\[\d{2}:", line): continue
        match = re.search(r"\[(\d{2}):(\d{2}\.\d{2})\]", line)
        if not match: match = re.search(r"\[(\d{2}):(\d{2})\]", line)
        
        if match:
            m, s = match.groups()
            sec = int(m)*60 + float(s)
            # 洗掉字級時間標籤與括號
            txt = re.sub(r"\[.*?\]|<.*?>|\{.*?\}|\(.*?\)", "", line).strip()
            if txt:
                parsed_lines.append({"count_idx": c_idx, "seconds": sec, "lyric": txt, "ts": f"{m}:{s}"})
                c_idx += 1
    
    # 處理結構 Tag
    maybe_json = re.search(r"\{.*\}", lrc_content, re.DOTALL)
    struct = json.loads(maybe_json.group(0)).get("song_structure") if maybe_json else None
    milestones = []
    if struct:
        for item in struct:
            for tag, l_num in item.items():
                target = int(l_num)
                ml = next((x for x in parsed_lines if x['count_idx'] == target), None)
                if ml: 
                    m_copy = ml.copy()
                    m_copy['tag'] = tag
                    milestones.append(m_copy)
    else: milestones = parsed_lines

    final_tl, last_t = [], 0.0
    if not milestones or milestones[0]['seconds'] > 0:
        final_tl.append({"ts": "00:00.00", "tag": "START", "lyric": "Opening Scene", "seconds": 0.0, "count_idx": -1})
    
    for m in sorted(milestones, key=lambda x: x['seconds']):
        while m['seconds'] - last_t > 10.5:
            last_t += 10.0
            if m['seconds'] - last_t > 1.0:
                final_tl.append({"ts": f"{int(last_t//60):02}:{last_t%60:05.2f}", "tag": "GAP", "lyric": "Transition Scene", "seconds": last_t, "count_idx": -1})
            else: break
        if 'tag' not in m: m['tag'] = "Lyric"
        final_tl.append(m)
        last_t = m['seconds']

    while audio_duration - last_t > 10.0:
        last_t += 10.0
        final_tl.append({"ts": f"{int(last_t//60):02}:{last_t%60:05.2f}", "tag": "END", "lyric": "Outro / Ending", "seconds": last_t, "count_idx": -1})
    return final_tl

# --- 4. 渲染邏輯 ---
if lrc_file and mp3_file:
    if "audio_dur" not in st.session_state:
        with open("active_temp.mp3", "wb") as f: f.write(mp3_file.getvalue())
        st.session_state.audio_dur = AudioFileClip("active_temp.mp3").duration
    
    timeline = parse_perfect_logic(lrc_file.getvalue().decode("utf-8", errors="ignore"), st.session_state.audio_dur)
    
    if st.session_state.get("is_running_batch", False):
        diag = st.empty()
        for i, item in enumerate(timeline):
            imk = f"img_{i}"
            if imk not in st.session_state:
                pk = f"p_{i}"
                if pk not in st.session_state: st.session_state[pk] = get_dynamic_prompt(style_category, style_map[style_category], item['tag'], i)
                diag.warning(f"正在產圖 ({i+1}/{len(timeline)})")
                res = call_openai_api(st.session_state[pk], diag)
                if res:
                    with open(f"{IMG_DIR}/f_{i}.png", "wb") as f: f.write(base64.b64decode(res))
                    st.session_state[imk] = res; st.rerun()
        st.session_state.is_running_batch = False; st.rerun()

    # --- 顯示分鏡列表 ---
    for i, item in enumerate(timeline):
        c1, c2, c3, c4 = st.columns([1.5, 4, 4, 1.8])
        c1.markdown(f"**{item['ts']}**")
        c1.caption(f"📌 {item['tag']}\n\n📝 {item['lyric']}")
        
        pk, imk = f"p_{i}", f"img_{i}"
        if pk not in st.session_state.row_versions: st.session_state.row_versions[pk] = 0
        if pk not in st.session_state: st.session_state[pk] = get_dynamic_prompt(style_category, style_map[style_category], item['tag'], i)
        
        current_v = f"v{st.session_state.global_v}_row{st.session_state.row_versions[pk]}"
        st.session_state[pk] = c2.text_area("", st.session_state[pk], key=f"t_{i}_{current_v}", height=120, label_visibility="collapsed")
        
        if imk in st.session_state:
            c3.markdown(f'<img src="data:image/png;base64,{st.session_state[imk]}" style="width:100%; border-radius:8px;">', unsafe_allow_html=True)
            c4.download_button("💾 下載圖", base64.b64decode(st.session_state[imk]), f"img_{i}.png", key=f"dl_{i}")

        col_a, col_b = c4.columns(2)
        if col_a.button("🔄 換劇本", key=f"refresh_{i}"):
            st.session_state.row_versions[pk] += 1
            st.session_state[pk] = get_dynamic_prompt(style_category, style_map[style_category], item['tag'], i + st.session_state.row_versions[pk])
            st.rerun()
        if col_b.button("🎨 產圖", key=f"btn_{i}"):
            res = call_openai_api(st.session_state[pk], st.empty())
            if res:
                with open(f"{IMG_DIR}/f_{i}.png", "wb") as f: f.write(base64.b64decode(res))
                st.session_state[imk] = res; st.rerun()
        st.divider()
