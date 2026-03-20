import PIL.Image
from PIL import Image
if not hasattr(PIL.Image, 'ANTIALIAS'):
    PIL.Image.ANTIALIAS = PIL.Image.LANCZOS

import streamlit as st
import re, requests, json, time, random, os, base64, sys

# --- 核心導入 ---
try:
    from moviepy import ImageClip, AudioFileClip, concatenate_videoclips, CompositeVideoClip
except:
    from moviepy.editor import ImageClip, AudioFileClip, concatenate_videoclips, CompositeVideoClip

# --- 1. 配置與安全 ---
st.set_page_config(page_title="MV Visual Director 24.5", layout="wide")

if "OPENAI_API_KEY" in st.secrets:
    API_KEY = st.secrets["OPENAI_API_KEY"]
else:
    st.error("❌ 請在 Streamlit Secrets 設置 OPENAI_API_KEY")
    st.stop()

IMG_DIR = "generated_frames"
if not os.path.exists(IMG_DIR): os.makedirs(IMG_DIR)

if "global_v" not in st.session_state: st.session_state.global_v = 0
if "row_versions" not in st.session_state: st.session_state.row_versions = {}

# --- 2. 側邊欄 ---
with st.sidebar:
    st.header("🔑 導演認證")
    correct_password = st.secrets.get("DIRECTOR_PASSWORD", "mv888")
    input_pw = st.text_input("輸入導演通行碼", type="password")
    if input_pw != correct_password:
        st.warning("🔒 請輸入正確密碼以解鎖導演台")
        st.stop() 
    st.success("✅ 認證成功")
    st.divider()

    st.header("🤖 模型配置")
    image_model_choice = st.selectbox("🎨 選擇產圖畫師", ["DALL-E 3 (精美/16:9)", "DALL-E 2 (便宜/1:1)"], index=0)
    selected_model = "dall-e-3" if "DALL-E 3" in image_model_choice else "dall-e-2"
    img_size = "1792x1024" if selected_model == "dall-e-3" else "1024x1024"

    st.header("🎵 素材導入")
    lrc_file = st.file_uploader("1. 上傳 LRC", type=["lrc"])
    mp3_file = st.file_uploader("2. 上傳 MP3", type=["mp3"])
    style_category = st.selectbox("Style", ["Gufeng", "R&B", "Lo-fi", "KTV", "Neon", "Film"])
    
    style_map = {
        "Gufeng": "Cinematic photorealistic Gufeng, 8k, traditional Chinese architecture, silk textures, golden hour sunlight, 16:9.",
        "R&B": "R&B soul vibe, purple and gold lighting, high contrast.",
        "Lo-fi": "Chill Lo-fi aesthetic, muted colors, cozy bedroom, grainy texture.",
        "KTV": "Classic KTV 90s style, VHS blurry texture, colorful neon glow.",
        "Neon": "Neon Cyberpunk, magenta and cyan glow, futuristic city.",
        "Film": "Cinematic 35mm film, professional color grading, film grain."
    }

    if st.button("🚀 啟動批量產圖"): st.session_state.is_running_batch = True
    if st.button("🎬 合成滿版 16:9 MV"): st.session_state.trigger_video_export = True
    if st.button("🗑️ 清除所有暫存"):
        st.session_state.clear()
        import shutil
        if os.path.exists(IMG_DIR): shutil.rmtree(IMG_DIR)
        os.makedirs(IMG_DIR); st.rerun()

# --- 3. 核心函數 ---
def get_dynamic_prompt(style_label, style_cmd, tag, seed_val):
    random.seed(seed_val + st.session_state.global_v + int(time.time()))
    prefixes = ["A stunning", "A majestic", "A vibrant", "A breathtaking", "A sharp", "An ethereal"]
    angles = ["cinematic wide shot", "macro close-up", "low angle view", "wide-angle lens shot"]
    
    if "Gufeng" in style_label:
        elements = ["ornate crimson palace walls", "ancient red wooden pavilion", "vibrant silk lanterns", "carved stone bridge", "blooming plum blossoms"]
    else:
        elements = ["vast scenery", "intricate texture", "distant horizon", "natural landscape"]
    
    lighting = ["intense golden hour glow", "vivid amber sunlight", "high contrast shadows", "soft moonlight"]
    base = f"{random.choice(prefixes)} {random.choice(angles)} of {random.choice(elements)}"
    return f"[{style_label}] {base}, {style_cmd}, {tag}, {random.choice(lighting)}, 8k, photorealistic, 16:9. NO PEOPLE, NO TEXT."

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
            txt = re.sub(r"\[.*?\]|<.*?>|\{.*?\}|\(.*?\)", "", line).strip()
            if txt:
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
                if ml: 
                    m_copy = ml.copy(); m_copy['tag'] = tag; milestones.append(m_copy)
    else: milestones = parsed_lines

    final_tl, last_t = [], 0.0
    if not milestones or milestones[0]['seconds'] > 0:
        final_tl.append({"ts": "00:00.00", "tag": "START", "lyric": "Opening Scene", "seconds": 0.0})
    for m in sorted(milestones, key=lambda x: x['seconds']):
        while m['seconds'] - last_t > 10.5:
            last_t += 10.0
            final_tl.append({"ts": f"{int(last_t//60):02}:{last_t%60:05.2f}", "tag": "GAP", "lyric": "Transition Scene", "seconds": last_t})
        m['tag'] = m.get('tag', 'Lyric')
        final_tl.append(m); last_t = m['seconds']
    while audio_duration - last_t > 10.0:
        last_t += 10.0
        final_tl.append({"ts": f"{int(last_t//60):02}:{last_t%60:05.2f}", "tag": "END", "lyric": "Ending Outro", "seconds": last_t})
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
            imk, pk = f"img_{i}", f"p_{i}"
            if imk not in st.session_state:
                if pk not in st.session_state: st.session_state[pk] = get_dynamic_prompt(style_category, style_map[style_category], item['tag'], i)
                diag.warning(f"正在批量產圖 ({i+1}/{len(timeline)})")
                res = call_openai_api(st.session_state[pk], diag)
                if res:
                    fpath = f"{IMG_DIR}/f_{i}_{int(time.time())}.png"
                    with open(fpath, "wb") as f: f.write(base64.b64decode(res))
                    st.session_state[f"path_{i}"] = fpath
                    st.session_state[imk] = res; st.rerun()
        st.session_state.is_running_batch = False; st.rerun()

    st.subheader("🎬 導演分鏡表")
    for i, item in enumerate(timeline):
        c1, c2, c3, c4 = st.columns([1.5, 4, 4, 1.8])
        c1.markdown(f"**{item['ts']}**")
        c1.caption(f"📌 {item['tag']}\n📝 {item['lyric']}")
        
        pk, imk = f"p_{i}", f"img_{i}"
        if pk not in st.session_state.row_versions: st.session_state.row_versions[pk] = 0
        if pk not in st.session_state: st.session_state[pk] = get_dynamic_prompt(style_category, style_map[style_category], item['tag'], i)
        
        # 文案區
        st.session_state[pk] = c2.text_area("劇本內容", st.session_state[pk], key=f"t_{i}_{st.session_state.row_versions[pk]}", height=120, label_visibility="collapsed")
        
        if imk in st.session_state:
            c3.markdown(f'<img src="data:image/png;base64,{st.session_state[imk]}" style="width:100%; border-radius:8px;">', unsafe_allow_html=True)
            c4.download_button("💾 下載圖", base64.b64decode(st.session_state[imk]), f"img_{i}.png", key=f"dl_{i}")

        col_a, col_b = c4.columns(2)
        if col_a.button("🔄 換劇本", key=f"ref_{i}"):
            st.session_state.row_versions[pk] += 1
            st.session_state[pk] = get_dynamic_prompt(style_category, style_map[style_category], item['tag'], i + st.session_state.row_versions[pk])
            st.rerun()
        if col_b.button("🎨 產圖", key=f"gen_{i}"):
            res = call_openai_api(st.session_state[pk], st.empty())
            if res:
                fpath = f"{IMG_DIR}/f_{i}_{int(time.time())}.png"
                with open(fpath, "wb") as f: f.write(base64.b64decode(res))
                st.session_state[f"path_{i}"] = fpath
                st.session_state[imk] = res; st.rerun()
        st.divider()

    # --- 5. 影片合成 (Pillow 預處理版) ---
    if st.session_state.get("trigger_video_export", False):
        st.session_state.trigger_video_export = False 
        with st.spinner("🎬 正在合成 16:9 滿版 MV..."):
            try:
                audio = AudioFileClip("active_temp.mp3")
                final_clips = []
                for i, item in enumerate(timeline):
                    fpath = st.session_state.get(f"path_{i}", f"{IMG_DIR}/f_{i}.png")
                    if os.path.exists(fpath):
                        with Image.open(fpath) as img:
                            w, h = img.size
                            target_w = 1920
                            target_h = int(h * (1920 / w))
                            img = img.resize((target_w, target_h), Image.LANCZOS)
                            top = (target_h - 1080) / 2
                            img = img.crop((0, top, 1920, top + 1080))
                            temp_p = f"{IMG_DIR}/render_{i}.jpg"
                            img.convert("RGB").save(temp_p, quality=95)
                        c = ImageClip(temp_p)
                        st_t, dur = item["seconds"], max(0.5, (timeline[i+1]["seconds"] if i+1 < len(timeline) else audio.duration) - item["seconds"])
                        c = c.with_start(st_t) if hasattr(c, "with_start") else c.set_start(st_t)
                        c = c.with_duration(dur) if hasattr(c, "with_duration") else c.set_duration(dur)
                        final_clips.append(c)

                if final_clips:
                    video = CompositeVideoClip(final_clips, size=(1920, 1080))
                    video = video.with_audio(audio) if hasattr(video, "with_audio") else video.set_audio(audio)
                    out_name = f"MV_{int(time.time())}.mp4"
                    video.write_videofile(out_name, fps=24, codec="libx264", audio_codec="aac")
                    st.success("✨ MV 合成完成！")
                    with open(out_name, "rb") as f:
                        st.download_button("📥 點我下載成品影片", f, file_name=out_name)
            except Exception as e: st.error(f"💥 合成失敗：{str(e)}")
