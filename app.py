import streamlit as st
import pandas as pd
import os
import zipfile

# Set browser tab title and layout
st.set_page_config(page_title="Gen 4 AI Tournament Battle Logs", layout="wide")

# --- SIDEBAR: GAME & TOURNAMENT SELECTION ---
st.sidebar.header("Game & Format")

# Game Selection 
game_choice = st.sidebar.selectbox(
    "Game Version:",
    ["Pokémon Platinum", "Pokémon HeartGold / SoulSilver"]
)

prefix = "hgss_" if game_choice == "Pokémon HeartGold / SoulSilver" else ""
game_title = "HGSS" if game_choice == "Pokémon HeartGold / SoulSilver" else "Pokémon Platinum"

format_choice = st.sidebar.radio(
    "Tournament Format:",
    ["Normal Levels", "Level 50", "Level 100"]
)

if format_choice == "Normal Levels":
    csv_file = f"{prefix}standings.csv"
    results_dir = f"{prefix}tournament_results"
elif format_choice == "Level 50":
    csv_file = f"{prefix}standings_50.csv"
    results_dir = f"{prefix}tournament_results_50"
else:
    csv_file = f"{prefix}standings_100.csv"
    results_dir = f"{prefix}tournament_results_100"

st.title(f"{game_title} AI Tournament: Battle Logs")

# --- LOAD DATA & CACHE ZIP CONTENTS ---
@st.cache_data
def load_data(csv_path):
    if not os.path.exists(csv_path):
        return None
    return pd.read_csv(csv_path)

df = load_data(csv_file)

if df is None:
    st.error(f"⚠️ Could not find `{csv_file}`. Tournament has not been run yet.")
    st.stop()

trainer_dict = dict(zip(df['Display_Name'], df['Trainer_Key']))

@st.cache_data
def get_available_logs(target_dir):
    """Scans local folders and split zips to build a fast index of all available logs."""
    available_files = set()
    
    # 1. Check local unzipped folder if it still exists (for local testing)
    if os.path.exists(target_dir):
        available_files.update(os.listdir(target_dir))
        
    # 2. Check all possible chunked zip files (for GitHub)
    for i in range(1, 21):
        zip_path = f"{target_dir}_part{i}.zip"
        if os.path.exists(zip_path):
            try:
                with zipfile.ZipFile(zip_path, 'r') as z:
                    # Strip folder paths out so we just have the raw filenames
                    available_files.update([os.path.basename(f) for f in z.namelist()])
            except zipfile.BadZipFile:
                pass
                
    return available_files

# Instantly load the index of all files so the Game 3 filter doesn't crash the server
available_logs = get_available_logs(results_dir)

# --- SIDEBAR: FILTERS ---
st.sidebar.markdown("---")
st.sidebar.header("🔍 Filter Options")

# 1. Fixed Tier Sorting
tier_priority = {
    "S+": 0, "S": 1, "S-": 2,
    "A+": 3, "A": 4, "A-": 5,
    "B+": 6, "B": 7, "B-": 8,
    "C+": 9, "C": 10, "C-": 11,
    "D+": 12, "D": 13, "D-": 14,
    "E+": 15, "E": 16, "E-": 17,
    "F+": 18, "F": 19, "F-": 20
}

available_tiers = df['Tier'].dropna().unique().tolist()
sorted_tiers = sorted(available_tiers, key=lambda x: tier_priority.get(x, 99))
tiers = ["All"] + sorted_tiers
selected_tier = st.sidebar.selectbox("Filter by Tier", tiers)

# 2. Class Filter
classes = ["All"] + sorted(df['Class'].dropna().unique().tolist())
selected_class = st.sidebar.selectbox("Filter by Trainer Class", classes)

# 3. Targeted Pokémon Filter
st.sidebar.markdown("---")
search_mon = st.sidebar.text_input("Filter by Pokémon", placeholder="e.g. Infernape, Garchomp").strip()

st.sidebar.markdown("**Apply Pokémon filter to:**")
pk_col1, pk_col2 = st.sidebar.columns(2)
with pk_col1:
    filter_t1_mon = st.checkbox("Trainer 1", value=True)
with pk_col2:
    filter_t2_mon = st.checkbox("Trainer 2", value=False)

# 4. Game 3 Filter
st.sidebar.markdown("---")
require_game_3 = st.sidebar.checkbox("Only matches that went to Game 3")

# 5. Display Options
st.sidebar.header("Display Settings")
expand_log = st.sidebar.checkbox("Show full log (Disable scrolling)", value=False)

# --- FILTER APPLICATION ---
base_df = df.copy()
if selected_tier != "All":
    base_df = base_df[base_df['Tier'] == selected_tier]
if selected_class != "All":
    base_df = base_df[base_df['Class'] == selected_class]

t1_df = base_df.copy()
if search_mon and filter_t1_mon:
    t1_df = t1_df[t1_df['Team_and_Movesets'].str.contains(search_mon, case=False, na=False)]

t2_df = base_df.copy()
if search_mon and filter_t2_mon:
    t2_df = t2_df[t2_df['Team_and_Movesets'].str.contains(search_mon, case=False, na=False)]

t1_names = sorted(t1_df['Display_Name'].dropna().unique().tolist())
t2_names = sorted(t2_df['Display_Name'].dropna().unique().tolist())

# --- MAIN SELECTION UI ---
st.markdown("---")
col1, col2, col3 = st.columns([2, 2, 1])

with col1:
    t1_name = st.selectbox(
        "Select Trainer 1",
        t1_names if t1_names else ["No trainers match filters"]
    )

t2_options = t2_names
if require_game_3 and t1_name != "No trainers match filters":
    t1_key = trainer_dict[t1_name]
    t1_display_safe = t1_name.replace(" ", "_")
    
    valid_t2s = []
    for t2 in t2_names:
        if t2 == t1_name:
            continue
        
        t2_key = trainer_dict[t2]
        t2_display_safe = t2.replace(" ", "_")
        
        possible_filenames = [
            f"{t1_display_safe}_vs_{t2_display_safe}_game3.txt",
            f"{t2_display_safe}_vs_{t1_display_safe}_game3.txt",
            f"{t1_key}_vs_{t2_key}_game3.txt",
            f"{t2_key}_vs_{t1_key}_game3.txt"
        ]
        
        # Check against our fast cached index instead of touching the hard drive!
        if any(f in available_logs for f in possible_filenames):
            valid_t2s.append(t2)
            
    t2_options = valid_t2s

with col2:
    default_idx = 1 if len(t2_options) > 1 and t2_options[0] == t1_name else 0
    t2_name = st.selectbox(
        "Select Trainer 2",
        t2_options if t2_options else ["No matching opponents found"],
        index=default_idx
    )

with col3:
    game_opts = ["Game 3", "Game 1", "Game 2"] if require_game_3 else ["Game 1", "Game 2", "Game 3"]
    game_num = st.selectbox("Select Game", game_opts)

# --- LOG RETRIEVAL AND DISPLAY ---
invalid_placeholders = ["No trainers match filters", "No matching opponents found"]
if t1_name and t2_name and t1_name not in invalid_placeholders and t2_name not in invalid_placeholders:
    if t1_name == t2_name:
        st.warning("Please select two different trainers.")
    else:
        t1_key = trainer_dict[t1_name]
        t2_key = trainer_dict[t2_name]
        
        t1_display_safe = t1_name.replace(" ", "_")
        t2_display_safe = t2_name.replace(" ", "_")
        game_suffix = game_num.replace(" ", "").lower()
        
        possible_filenames = [
            f"{t1_display_safe}_vs_{t2_display_safe}_{game_suffix}.txt",
            f"{t2_display_safe}_vs_{t1_display_safe}_{game_suffix}.txt",
            f"{t1_key}_vs_{t2_key}_{game_suffix}.txt",
            f"{t2_key}_vs_{t1_key}_{game_suffix}.txt"
        ]
        
        # Find which filename actually exists in our index
        target_filename = next((f for f in possible_filenames if f in available_logs), None)
        log_content = None

        if target_filename:
            # First, try to read from local unzipped folder (if it exists)
            raw_path = os.path.join(results_dir, target_filename)
            if os.path.exists(raw_path):
                with open(raw_path, 'r', encoding='utf-8') as f:
                    log_content = f.read()
            else:
                # If not in raw folder, search through the chunked zips
                for i in range(1, 21):
                    zip_path = f"{results_dir}_part{i}.zip"
                    if os.path.exists(zip_path):
                        with zipfile.ZipFile(zip_path, 'r') as z:
                            zip_files = z.namelist()
                            
                            # Handle structure where files are inside a parent folder in the zip
                            path_with_dir = f"{results_dir}/{target_filename}"
                            actual_zip_path = path_with_dir if path_with_dir in zip_files else (target_filename if target_filename in zip_files else None)
                            
                            if actual_zip_path:
                                with z.open(actual_zip_path) as f:
                                    log_content = f.read().decode('utf-8')
                                break # Stop checking this zip
                                
                    if log_content:
                        break # Stop looping through parts
                        
        if log_content:
            st.success(f"📄 Loaded log: `{target_filename}`")
            
            if expand_log:
                st.code(log_content, language="text")
            else:
                st.text_area("Battle Log", log_content, height=520, label_visibility="collapsed")
        else:
            if game_num == "Game 3":
                st.info("No Game 3 log found. This match ended in a 2-0 sweep!")
            else:
                st.error(f"Could not find a battle log for **{t1_name}** vs **{t2_name}**.")