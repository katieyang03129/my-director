import streamlit as st
import re, requests, json, time, random, os, base64, sys

# --- 核心導入 ---
try:
    from moviepy import ImageClip, AudioFileClip, concatenate_videoclips, CompositeVideoClip
except:
    from moviepy.editor import ImageClip, AudioFileClip, concatenate_videoclips, CompositeVideoClip

# --- 1. 安全配置與權限控管 ---
st.set_page_config(page_title="MV Visual Director (Cloud Sync)", layout="wide")

# 從後台讀取金鑰 (若後台沒設，則預留手動輸入)
if "OPENAI_API_KEY" in st.secrets:
    API_KEY = st.secrets["OPENAI_API_KEY"]
else:
    API_KEY = "" # 或是讓使用者在畫面手動輸入

IMG_DIR = "generated_frames"
if not os.path.exists(IMG_DIR): os.makedirs(IMG_DIR)

# 初始化狀態
if "global_v" not in st.session_state: st.session_state.global_v = 0
if "row_versions" not in st.session_state: st.session_state.row_versions = {}

# --- 2. 側邊欄與密碼防護 ---
with st.sidebar:
    st.header("🔑 導演認證")
    # 這是妳的分享密碼，可以隨意修改
    director_pw = st.text_input("輸入導演通行碼", type="password")
    is_authorized = (director_pw == "mv888") # <--- 這裡設定妳的分享密碼
    
    if not is_authorized:
        st.warning("請輸入正確密碼以啟用系統")
        st.stop() # 密碼不對就停止執行下方代碼

    st.success("認證成功！系統已就緒")
    st.divider()
    
    st.header("🎵 素材導入")
    lrc_file = st.file_uploader("1. 上傳 LRC", type=["lrc"])
    mp3_file = st.file_uploader("2. 上傳 MP3", type=["mp3"])
    
    st.divider()
    style_category = st.selectbox("Style", ["Gufeng_Real", "R&B", "Lo-fi", "KTV", "Neon", "Film"])
    
    style_map = {
        "Gufeng_Real": "Cinematic photorealistic Gufeng, 8k resolution, vivid rich colors, deep saturation, traditional Chinese architecture, intricate silk textures, golden hour sunlight, sharp details, movie scene aesthetic.",
        "R&B": "R&B soul vibe, purple and gold lighting, smooth velvet shadows.",
        "Lo-fi": "Chill Lo-fi aesthetic, muted colors, cozy bedroom, grainy nostalgic vibe.",
        "KTV": "Classic KTV 90s style, VHS blurry texture, amateur photography snapshots.",
        "Neon": "Neon Cyberpunk, magenta and cyan glow, wet street reflections, urban fog.",
        "Film": "Cinematic 35mm film, professional color grading, anamorphic flares."
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

# --- 3. 核心函數 (維持 24.6 實景邏輯) ---

def get_dynamic_prompt(style_label, style_cmd, tag, seed_val):
    random.seed(seed_val + st.session_state.global_v + time.time())
    prefixes = ["A stunning", "A majestic", "A vibrant", "A breathtaking", "A sharp", "A high-contrast"]
    angles = ["cinematic wide shot", "macro close-up", "low angle view", "side profile"]
    
    if "Gufeng" in style_label:
        elements = ["ornate crimson palace walls", "ancient red wooden pavilion", "vibrant silk lanterns", "highly detailed carved stone bridge", "blooming scarlet plum blossoms"]
    else:
        elements = ["urban scenery", "nature detail", "abstract texture", "distant horizon"]
    
    lighting = ["intense golden hour glow", "vivid amber sunlight", "clear sky with high contrast shadows"]
    random.shuffle(prefixes)
    base = f"[{style_label}] {random.choice(prefixes)} {random.choice(angles)}"
    return f"{base} of {random.choice(elements)}, {style_cmd}, {random.choice(lighting)}, 8k, photorealistic, 16:9. NO PEOPLE, NO TEXT."

def call_openai_api(prompt, diag):
    if not API_KEY:
        st.error("❌ 尚未配置 API KEY")
        return None
    url = "https://api.openai.com/v1/images/generations"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {API_KEY}"}
    payload = {"model": "gpt-image-1-mini", "prompt": str(prompt), "n": 1, "size": "1536x1024"}
    try:
        res = requests.post(url, headers=headers, data=json.dumps(payload).encode('utf-8'), timeout=45)
        rj = res.json()
        if res.status_code == 200:
            d = rj['data'][0]
            return d['b64_json'] if 'b64_json' in d else base64.b64encode(requests.get(d['url']).content).decode('utf-8')
    except: pass
    return None

def parse_perfect_logic(lrc_content, audio_duration):
    raw_lines = lrc_content.split('\n')
    parsed_lines = []
    c_idx = 0
    for line in raw_lines:
        if line.startswith('{') or not line.strip() or not re.search(r"\[\d{2}:", line): continue
        match = re.search(r"\[(\d{2}):(\d{2}\.\d{2})\]", line)
        if match:
            m, s = match.groups()
            sec = int(m)*60 + float(s)
            txt = re.sub(r"\[.*?\]|<[^>]+>|\([^)]+\)", "", line).strip()
            parsed_lines.append({"count_idx": c_idx, "seconds": sec, "lyric": txt, "ts": f"{m}:{s}"})
            c_idx += 1
    
    maybe_json = re.search(r"\{.*\}", lrc_content, re.DOTALL)
    struct = json.loads(maybe_json.group(0)).get("song_structure") if maybe_json else None
    milestones = []
    if struct:
        for item in struct:
            for tag, l_num in item.items():
                target = int(l_num)
                ml = next((x for x in parsed_lines if x['count_idx'] == target), None)
                if ml: milestones.append({"seconds": ml['seconds'], "tag": tag, "lyric": ml['lyric'], "count_idx": target, "ts": ml['ts']})
    
    final_tl, last_t = [], 0.0
    if not milestones or milestones[0]['seconds'] > 0:
        final_tl.append({"ts": "00:00.00", "tag": "START", "lyric": "Opening", "seconds": 0.0, "count_idx": -1})
    
    for m in sorted(milestones, key=lambda x: x['seconds']):
        while m['seconds'] - last_t > 10.5:
            last_t += 10.0
            if m['seconds'] - last_t > 1.0:
                final_tl.append({"ts": f"{int(last_t//60):02}:{last_t%60:05.2f}", "tag": "GAP", "lyric": "Transition", "seconds": last_t, "count_idx": -1})
            else: break
        final_tl.append(m)
        last_t = m['seconds']

    while audio_duration - last_t > 10.0:
        last_t += 10.0
        final_tl.append({"ts": f"{int(last_t//60):02}:{last_t%60:05.2f}", "tag": "END", "lyric": "Outro", "seconds": last_t, "count_idx": -1})
    return final_tl

# --- 4. 介面渲染 ---
if lrc_file and mp3_file:
    if "audio_dur" not in st.session_state:
        with open("active_temp.mp3", "wb") as f: f.write(mp3_file.getvalue())
        st.session_state.audio_dur = AudioFileClip("active_temp.mp3").duration
    
    timeline = parse_perfect_logic(lrc_file.getvalue().decode("utf-8", errors="ignore"), st.session_state.audio_dur)
    
    if st.session_state.get("is_running_batch", False):
        diag = st.empty()
        for i, item in enumerate(timeline):
            if f"img_{i}" not in st.session_state:
                pk = f"p_{i}"
                if pk not in st.session_state: st.session_state[pk] = get_dynamic_prompt(style_category, style_map[style_category], item['tag'], i)
                diag.warning(f"正在產圖 ({i+1}/{len(timeline)})")
                res = call_openai_api(st.session_state[pk], diag)
                if res:
                    with open(f"{IMG_DIR}/f_{i}.png", "wb") as f: f.write(base64.b64decode(res))
                    st.session_state[f"img_{i}"] = res; st.rerun()
        st.session_state.is_running_batch = False; st.rerun()

    if st.session_state.get("trigger_video_export"):
        with st.spinner("🎬 雲端合成中...這可能需要幾分鐘"):
            try:
                final_clips, audio = [], AudioFileClip("active_temp.mp3")
                for i, item in enumerate(timeline):
                    fpath = f"{IMG_DIR}/f_{i}.png"
                    if os.path.exists(fpath):
                        start_t, end_t = item["seconds"], (timeline[i+1]["seconds"] if i+1 < len(timeline) else st.session_state.audio_dur)
                        dur = end_t - start_t
                        c = ImageClip(fpath).with_duration(dur).resized(width=1920) if hasattr(ImageClip(fpath), "with_duration") else ImageClip(fpath).set_duration(dur).resize(width=1920)
                        y_center = c.h / 2
                        c = c.cropped(y1=y_center-540, y2=y_center+540, x1=0, x2=1920) if hasattr(c, "cropped") else c.crop(y1=y_center-540, y2=y_center+540, x1=0, x2=1920)
                        c = c.with_start(start_t) if hasattr(c, "with_start") else c.set_start(start_t)
                        final_clips.append(c)
                if final_clips:
                    final_v = CompositeVideoClip(final_clips, size=(1920, 1080))
                    final_v = final_v.with_audio(audio) if hasattr(final_v, "with_audio") else final_v.set_audio(audio)
                    final_v.write_videofile("final_mv.mp4", fps=24, codec="libx264", audio_codec="aac")
                    st.success("✅ 合成完畢！")
                    st.download_button("💾 下載滿版成品", open("final_mv.mp4", "rb"), "final_mv.mp4")
            except Exception as e: st.error(f"合成失敗: {e}")
        st.session_state.trigger_video_export = False

    for i, item in enumerate(timeline):
        c1, c2, c3, c4 = st.columns([1.5, 4, 4, 1.8])
        c1.markdown(f"**{item['ts']}**")
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