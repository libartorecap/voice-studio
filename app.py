import streamlit as st
import edge_tts
import asyncio
from pydub import AudioSegment
import os
import uuid
import pandas as pd

st.set_page_config(page_title="Voice Studio", page_icon="🎭", layout="wide")

# Fetch Voices
@st.cache_data
def get_voices():
    async def fetch():
        voices = await edge_tts.list_voices()
        return [v["ShortName"] for v in voices if v["Locale"].startswith("en-")]
    try:
        return asyncio.run(fetch())
    except Exception:
        return ["en-US-JennyNeural", "en-GB-RyanNeural", "en-US-ChristopherNeural"]

AVAILABLE_VOICES = get_voices()

async def generate_line(text, voice, rate_str, filename):
    communicate = edge_tts.Communicate(text, voice, rate=rate_str)
    await communicate.save(filename)

# Initialize Roster in memory
if "roster" not in st.session_state:
    st.session_state.roster = pd.DataFrame([
        {"Character Name": "Narrator", "Assigned Voice": "en-GB-RyanNeural", "Speed Rate (%)": 0},
        {"Character Name": "Captain Miller", "Assigned Voice": "en-US-ChristopherNeural", "Speed Rate (%)": 0}
    ])

st.title("🎭 Unlimited Character Voice Studio")
st.markdown("Create custom characters, preview voices, and generate your conversation. **Host for free!**")

col1, col2 = st.columns([1, 1.5])

with col1:
    st.subheader("👥 Character Roster")
    st.markdown("Edit directly in the table below to add/remove characters:")
    
    # Editable table!
    st.session_state.roster = st.data_editor(
        st.session_state.roster, 
        num_rows="dynamic",
        use_container_width=True
    )
    
    st.divider()
    st.subheader("🔊 Preview a Voice")
    preview_voice = st.selectbox("Select Voice to Preview", AVAILABLE_VOICES)
    preview_speed = st.slider("Speech Speed (%)", -50, 50, 0)
    
    if st.button("Preview"):
        with st.spinner("Generating preview..."):
            rate_str = f"{int(preview_speed):+d}%"
            temp_file = f"preview_{uuid.uuid4().hex}.mp3"
            asyncio.run(generate_line("Hello! This is a preview of my voice at this speed.", preview_voice, rate_str, temp_file))
            st.audio(temp_file)

    st.divider()
    fallback_voice = st.selectbox("Default / Fallback Voice", AVAILABLE_VOICES, index=0)

with col2:
    st.subheader("🎬 The Script")
    default_script = """Narrator: Deep space vessel Horizon, day 402.

Captain Miller: Report on the engine anomaly.
Pause: 1
Narrator: The console beeped loudly."""

    script_text = st.text_area("Write your script here (Leave blank lines for natural pauses):", value=default_script, height=350)
    
    if st.button("🎬 Generate Complete Conversation", type="primary", use_container_width=True):
        with st.spinner("Stitching audio together... Please wait."):
            voice_map = {}
            rate_map = {}
            for _, row in st.session_state.roster.iterrows():
                name = str(row["Character Name"]).strip().lower()
                voice_map[name] = str(row["Assigned Voice"])
                rate_map[name] = f"{int(row['Speed Rate (%)']):+d}%"
            
            lines = script_text.split('\n')
            combined_audio = AudioSegment.empty()
            
            try:
                for line in lines:
                    line = line.strip()
                    if not line:
                        combined_audio += AudioSegment.silent(duration=1000)
                        continue
                        
                    if line.lower().startswith("pause"):
                        try:
                            val = line.split(":")[-1].strip() if ":" in line else line.lower().replace("pause", "").strip()
                            combined_audio += AudioSegment.silent(duration=int(float(val) * 1000))
                        except ValueError:
                            pass
                        continue
                        
                    if ":" in line:
                        char, text = line.split(":", 1)
                        char = char.strip().lower()
                        
                        voice = voice_map.get(char, fallback_voice)
                        rate_str = rate_map.get(char, "+0%")
                        
                        temp_file = f"temp_{uuid.uuid4().hex}.mp3"
                        asyncio.run(generate_line(text.strip(), voice, rate_str, temp_file))
                        
                        combined_audio += AudioSegment.from_mp3(temp_file)
                        combined_audio += AudioSegment.silent(duration=200)
                        
                        if os.path.exists(temp_file):
                            os.remove(temp_file)
                            
                output_file = "final_conversation.mp3"
                combined_audio.export(output_file, format="mp3")
                st.success("Audio Generation Complete!")
                st.audio(output_file)
                
            except Exception as e:
                st.error(f"An error occurred: {e}")