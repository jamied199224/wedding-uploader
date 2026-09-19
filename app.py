import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
import io
import datetime

st.set_page_config(page_title="Miljam's Wedding Upload", page_icon="💍", layout="centered")

def init_connections():
    scope = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    # Streamlit natively reads the [GOOGLE_CREDENTIALS_JSON] table as a dictionary
    creds_dict = dict(st.secrets["GOOGLE_CREDENTIALS_JSON"])
    if "private_key" in creds_dict:
        creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
        
    creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
    gc = gspread.authorize(creds)
    drive_service = build('drive', 'v3', credentials=creds)
    return gc, drive_service

st.title("💍 Miljam's Wedding Day Memory Upload!")
st.write("Upload and View Shared Memories - Pictures and Videos welcome!")

uploader_name = st.text_input("Your Name / Family (Optional)", placeholder="Guest")

uploaded_files = st.file_uploader(
    "Choose photos or videos", 
    type=["jpg", "jpeg", "png", "mp4", "mov", "webm"], 
    accept_multiple_files=True
)

if uploaded_files and st.button("Upload Memories"):
    with st.spinner("Connecting to Google Drive..."):
        gc, drive_service = init_connections()
        folder_id = "1AjLAnQFpX_PMeXBkFPanOCwLcfeUrMJl" # Your Drive Folder ID
        sheet = gc.open("1qCaENpLHD9APb-DZ9pgyalpp37xNrUeJt4lps5b1IUo").sheet1 

    progress_bar = st.progress(0)
    status_text = st.empty()
    total_files = len(uploaded_files)

    for i, file in enumerate(uploaded_files):
        status_text.text(f"Uploading file {i+1} of {total_files}: {file.name}")
        
        file_metadata = {
            'name': file.name,
            'parents': [folder_id]
        }
        
        media = MediaIoBaseUpload(io.BytesIO(file.read()), mimetype=file.type, resumable=True)
        
        uploaded_file = drive_service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id, webViewLink'
        ).execute()

        file_id = uploaded_file.get('id')
        file_url = uploaded_file.get('webViewLink')

        drive_service.permissions().create(
            fileId=file_id,
            body={'role': 'viewer', 'type': 'anyone'}
        ).execute()

        sheet.append_row([file_id, file_url, uploader_name or 'Guest', str(datetime.datetime.now())])
        progress_bar.progress((i + 1) / total_files)

    st.success("All files uploaded successfully!")
