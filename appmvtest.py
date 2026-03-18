import PIL.Image
from PIL import Image  # 確保導入 PIL 處理圖像
# 解決 Pillow 10 移除 ANTIALIAS 導致 MoviePy 崩潰的問題
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
st.set_page_config(page_title="MV Visual Director 24.5 (Secure)", layout="wide")

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

    st.header("🤖 模型配置與預算")
    image_model_choice = st.selectbox("🎨 選擇產圖畫師", ["DALL-E 3 (精美/16:9)", "DALL-E 2 (便宜/1:1)"], index=0)
    if "DALL-E 3" in image_model_choice:
        selected_model, cost_twd, img_size = "dall-e-3", 1.3, "1792x1024"
    else:
        selected_model, cost_twd, img_size = "dall-e-2", 0.6, "1024x1024"

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
    prefixes = ["A stunning", "A majestic", "A vibrant", "A breathtaking"]
    angles = ["cinematic wide shot", "wide-angle lens shot"]
    elements = ["scenery", "texture", "horizon"]
    if "Gufeng" in style_label:
        elements = ["ornate crimson palace walls", "ancient red wooden pavilion", "vibrant silk lanterns", "carved stone bridge"]
    lighting = ["intense golden hour glow", "vivid amber sunlight"]
    return f"[{style_label}] {random.choice(prefixes)} {random.choice(angles)} of {random.choice(elements)}, {style_cmd}, {random.choice(lighting)}, 8k, photorealistic, 16:9. NO PEOPLE, NO TEXT."

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
        if not re.search(r"\[\d{2}:", line): continue
        match = re.search(r"\[(\d{2}):(\d{2}\.\d{2})\]", line)
        if not match: match = re.search(r"\[(\d{2}):(\d{2})\]", line)
        if match:
            m, s = match.groups()
            sec = int(m)*60 + float(s)
            txt = re.sub(r"\[.*?\]|<.*?>|\{.*?\}|\(.*?\)", "", line).strip()
            if txt:
                parsed_lines.append({"count_idx": c_idx, "seconds": sec, "lyric": txt, "ts": f"{m}:{s}"})
                c_idx += 1
    final_tl, last_t = [], 0.0
    if not parsed_lines or parsed_lines[0]['seconds'] > 0:
        final_tl.append({"ts": "00:00.00", "tag": "START", "lyric": "Opening Scene", "seconds": 0.0})
    for m in sorted(parsed_lines, key=lambda x: x['seconds']):
        while m['seconds'] - last_t > 10.5:
            last_t += 10.0
            final_tl.append({"ts": f"{int(last_t//60):02}:{last_t%60:05.2f}", "tag": "GAP", "lyric": "Transition", "seconds": last_t})
        m['tag'] = "Lyric"
        final_tl.append(m)
        last_t = m['seconds']
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
                if pk not in st.session_state: st.session_state[pk] = get_dynamic_prompt(style_category, style_map[style_category], item.get('tag',''), i)
                diag.warning(f"正在產圖 ({i+1}/{len(timeline)})")
                res = call_openai_api(st.session_state[pk], diag)
                if res:
                    with open(f"{IMG_DIR}/f_{i}.png", "wb") as f: f.write(base64.b64decode(res))
                    st.session_state[imk] = res; st.rerun()
        st.session_state.is_running_batch = False; st.rerun()

    for i, item in enumerate(timeline):
        c1, c2, c3, c4 = st.columns([1.5, 4, 4, 1.8])
        c1.markdown(f"**{item['ts']}**")
        c1.caption(f"📝 {item['lyric']}")
        pk, imk = f"p_{i}", f"img_{i}"
        if pk not in st.session_state: st.session_state[pk] = get_dynamic_prompt(style_category, style_map[style_category], item.get('tag',''), i)
        st.session_state[pk] = c2.text_area("", st.session_state[pk], key=f"t_{i}", height=100, label_visibility="collapsed")
        if imk in st.session_state:
            c3.markdown(f'<img src="data:image/png;base64,{st.session_state[imk]}" style="width:100%; border-radius:8px;">', unsafe_allow_html=True)
            if c4.button("🎨 產圖", key=f"btn_{i}"):
                res = call_openai_api(st.session_state[pk], st.empty())
                if res:
                    with open(f"{IMG_DIR}/f_{i}.png", "wb") as f: f.write(base64.b64decode(res))
                    st.session_state[imk] = res; st.rerun()
        st.divider()

    # --- 5. 影片合成執行區塊 (縮排正確版) ---
    if st.session_state.get("trigger_video_export", False):
        st.session_state.trigger_video_export = False 
        with st.spinner("🎬 正在使用 Pillow + MoviePy 雙引擎合成中..."):
            try:
                audio = AudioFileClip("active_temp.mp3")
                final_clips = []
                for i, item in enumerate(timeline):
                    fpath = f"{IMG_DIR}/f_{i}.png"
                    if os.path.exists(fpath):
                        start_t = item["seconds"]
                        end_t = timeline[i+1]["seconds"] if i+1 < len(timeline) else audio.duration
                        dur = max(0.5, end_t - start_t)
                        
                        # --- PIL 預處理裁切 ---
                        with Image.open(fpath) as img:
                            w, h = img.size
                            # 先縮放寬度到 1920
                            target_w = 1920
                            target_h = int(h * (target_w / w))
                            img = img.resize((target_w, target_h), Image.LANCZOS)
                            # 居中裁切成 1080 高度
                            top = (target_h - 1080) / 2
                            img = img.crop((0, top, 1920, top + 1080))
                            processed_path = f"{IMG_DIR}/p_{i}.jpg" # 轉存成 jpg 節省空間
                            img.convert("RGB").save(processed_path, quality=95)

                        c = ImageClip(processed_path)
                        # 版本相容時間設置
                        c = c.with_start(start_t) if hasattr(c, "with_start") else c.set_start(start_t)
                        c = c.with_duration(dur) if hasattr(c, "with_duration") else c.set_duration(dur)
                        final_clips.append(c)

                if final_clips:
                    video = CompositeVideoClip(final_clips, size=(1920, 1080)).set_audio(audio)
                    out_name = f"MV_{int(time.time())}.mp4"
                    video.write_videofile(out_name, fps=24, codec="libx264", audio_codec="aac")
                    st.success("✨ 16:9 滿版 MV 合成完成！")
                    with open(out_name, "rb") as f:
                        st.download_button("📥 點我下載成品影片", f, file_name=out_name)
                else:
                    st.error("❌ 沒有可合成的圖片")
            except Exception as e:
                st.error(f"💥 合成失敗：{str(e)}")
