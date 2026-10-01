import gradio as gr
import edge_tts
import asyncio
from pydub import AudioSegment
import os
import uuid
import pandas as pd

# 1. Fetch voices
async def get_english_voices():
    voices = await edge_tts.list_voices()
    return [v["ShortName"] for v in voices if v["Locale"].startswith("en-")]

AVAILABLE_VOICES = asyncio.run(get_english_voices())

async def generate_line(text, voice, rate_str, filename):
    communicate = edge_tts.Communicate(text, voice, rate=rate_str)
    await communicate.save(filename)

async def preview_voice(voice, rate_val):
    rate_str = f"{int(rate_val):+d}%"
    temp_filename = f"preview_{uuid.uuid4().hex}.mp3"
    text = "Hello! This is a preview of my voice at this speed."
    try:
        await generate_line(text, voice, rate_str, temp_filename)
        return temp_filename
    except Exception as e:
        print(f"Preview Error: {e}")
        return None

# 2. Roster Helpers
def add_or_update_character(char_name, selected_voice, rate_val, current_roster):
    char_name = char_name.strip()
    if not char_name:
        return current_roster, "Please provide a character name."
    
    df = current_roster if isinstance(current_roster, pd.DataFrame) else pd.DataFrame(current_roster, columns=["Character Name", "Assigned Voice", "Speed Rate (%)"])
    mask = df["Character Name"].str.strip().str.lower() == char_name.lower()
    
    if mask.any():
        df.loc[mask, "Assigned Voice"] = selected_voice
        df.loc[mask, "Speed Rate (%)"] = rate_val
        msg = f"Updated '{char_name}'."
    else:
        new_row = pd.DataFrame([{"Character Name": char_name, "Assigned Voice": selected_voice, "Speed Rate (%)": rate_val}])
        df = pd.concat([df, new_row], ignore_index=True)
        msg = f"Added '{char_name}'."
        
    return df, msg

def auto_detect_characters(script_text, current_roster, default_voice):
    df = current_roster if isinstance(current_roster, pd.DataFrame) else pd.DataFrame(current_roster, columns=["Character Name", "Assigned Voice", "Speed Rate (%)"])
    existing_chars = set(df["Character Name"].str.strip().str.lower().tolist())
    
    lines = script_text.strip().split("\n")
    new_entries = []
    
    for line in lines:
        line = line.strip()
        if ":" in line and not line.lower().startswith("pause"):
            name = line.split(":", 1)[0].strip()
            if name.lower() not in existing_chars and name.lower() not in [e["Character Name"].lower() for e in new_entries]:
                new_entries.append({"Character Name": name, "Assigned Voice": default_voice, "Speed Rate (%)": 0})
                
    if new_entries:
        df = pd.concat([df, pd.DataFrame(new_entries)], ignore_index=True)
        return df, f"Detected and added {len(new_entries)} character(s)."
    return df, "No new characters detected."

# 3. Async Scene Generator
async def parse_script_and_generate(script_text, roster_df, fallback_voice):
    voice_map = {}
    rate_map = {}
    
    if isinstance(roster_df, pd.DataFrame):
        for _, row in roster_df.iterrows():
            c_name = str(row["Character Name"]).strip().lower()
            voice_map[c_name] = str(row["Assigned Voice"]).strip()
            try:
                rate_val = int(row["Speed Rate (%)"])
            except ValueError:
                rate_val = 0
            rate_map[c_name] = f"{rate_val:+d}%"
    
    # Split the script into lines
    lines = script_text.split("\n")
    combined_audio = AudioSegment.empty()
    temp_files = []
    
    try:
        for line in lines:
            line = line.strip()
            
            # --- FIX: Handle Empty Blank Lines ---
            # If the user just left a blank line, add a 1-second pause automatically
            if not line:
                combined_audio += AudioSegment.silent(duration=1000)
                continue
                
            # --- FIX: Handle explicitly typed Pauses (e.g., Pause: 2.5) ---
            if line.lower().startswith("pause"):
                try:
                    # Extracts the number, even if they type "Pause 2" or "Pause: 2"
                    val = line.split(":")[-1].strip() if ":" in line else line.lower().replace("pause", "").strip()
                    pause_seconds = float(val)
                    combined_audio += AudioSegment.silent(duration=int(pause_seconds * 1000))
                except ValueError:
                    pass
                continue
                
            # Handle Dialogue
            if ":" in line:
                character, text = line.split(":", 1)
                character = character.strip().lower()
                text = text.strip()
                
                voice = voice_map.get(character, fallback_voice)
                rate_str = rate_map.get(character, "+0%")
                
                temp_filename = f"temp_{uuid.uuid4().hex}.mp3"
                temp_files.append(temp_filename)
                
                # Generate audio
                await generate_line(text, voice, rate_str, temp_filename)
                
                # Append to main audio track
                dialogue_audio = AudioSegment.from_mp3(temp_filename)
                combined_audio += dialogue_audio
                
                # Always add a tiny natural 0.2 second breathing gap between speakers
                combined_audio += AudioSegment.silent(duration=200)

        output_filename = "final_conversation.mp3"
        combined_audio.export(output_filename, format="mp3")
        return output_filename

    except Exception as e:
        print(f"Error during audio generation: {e}")
        raise gr.Error(f"Generation failed. Check Command Prompt for details.")
        
    finally:
        for temp_file in temp_files:
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except Exception:
                    pass

# 4. Gradio UI
sample_script = """Narrator: Deep space vessel Horizon, day 402.

Captain Miller: Report on the engine anomaly.

AI Core: Main reactor core fluctuation stands at 14 percent, Captain.
Pause: 2.5
Doctor Vance: Can we stabilize it before entering the atmosphere?

AI Core: Probability of containment is approximately 32 percent."""

initial_roster = pd.DataFrame([
    {"Character Name": "Narrator", "Assigned Voice": "en-GB-RyanNeural", "Speed Rate (%)": 0},
    {"Character Name": "Captain Miller", "Assigned Voice": "en-US-ChristopherNeural", "Speed Rate (%)": 0},
    {"Character Name": "AI Core", "Assigned Voice": "en-US-JennyNeural", "Speed Rate (%)": -10},
    {"Character Name": "Doctor Vance", "Assigned Voice": "en-US-GuyNeural", "Speed Rate (%)": 5}
])

with gr.Blocks(theme=gr.themes.Soft()) as app:
    gr.Markdown("# 🎭 Unlimited Character Voice Studio")
    
    with gr.Row():
        with gr.Column(scale=1):
            gr.Markdown("### 👥 Character Roster")
            roster_table = gr.Dataframe(value=initial_roster, headers=["Character Name", "Assigned Voice", "Speed Rate (%)"], datatype=["str", "str", "number"], interactive=True)
            
            with gr.Group():
                char_name_input = gr.Textbox(placeholder="Character Name", label="Add New Character")
                voice_select_dropdown = gr.Dropdown(choices=AVAILABLE_VOICES, value=AVAILABLE_VOICES[0], label="Voice")
                rate_slider = gr.Slider(minimum=-50, maximum=50, value=0, step=1, label="Speech Speed (%)")
                
                with gr.Row():
                    preview_btn = gr.Button("🔊 Preview Voice", variant="secondary")
                    add_btn = gr.Button("➕ Add / Update", variant="primary")
                    
                preview_audio = gr.Audio(label="Preview Audio", type="filepath", interactive=False)
                status_box = gr.Markdown("")
            
            scan_btn = gr.Button("🔍 Auto-Detect Characters from Script")
            fallback_dropdown = gr.Dropdown(choices=AVAILABLE_VOICES, value="en-US-JennyNeural", label="Fallback Voice")
            
        with gr.Column(scale=2):
            script_input = gr.Textbox(
                lines=16, 
                label="Script (Leave blank lines for natural pauses, or write 'Pause: 2' for exact seconds)", 
                value=sample_script
            )
            generate_btn = gr.Button("🎬 Generate Complete Conversation", variant="primary")
            audio_output = gr.Audio(label="Final Combined Audio", type="filepath")

    preview_btn.click(fn=preview_voice, inputs=[voice_select_dropdown, rate_slider], outputs=preview_audio)
    add_btn.click(fn=add_or_update_character, inputs=[char_name_input, voice_select_dropdown, rate_slider, roster_table], outputs=[roster_table, status_box])
    scan_btn.click(fn=auto_detect_characters, inputs=[script_input, roster_table, fallback_dropdown], outputs=[roster_table, status_box])
    generate_btn.click(fn=parse_script_and_generate, inputs=[script_input, roster_table, fallback_dropdown], outputs=audio_output)

if __name__ == "__main__":
    # If generating huge scripts crashes, change share=True to share=False
    app.launch(share=False, inbrowser=True)