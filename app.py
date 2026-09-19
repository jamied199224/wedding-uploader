import streamlit as st
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

# Page configuration
st.set_page_config(
    page_title="Wedding Media Uploader",
    page_icon="📷",
    layout="centered"
)

st.title("📷 Wedding Photo & Video Upload")
st.write("Please share your favorite moments and memories from the big day with us!")

# 1. Initialize Google API Credentials using Streamlit Secrets
@st.cache_resource
def get_google_services():
    try:
        creds = Credentials(
            token=None,
            refresh_token=st.secrets["refresh_token"],
            client_id=st.secrets["client_id"],
            client_secret=st.secrets["client_secret"],
            token_uri="https://oauth2.googleapis.com/token",
        )
        
        # Build the services securely within the sandboxed scope
        drive_service = build('drive', 'v3', credentials=creds)
        sheets_service = build('sheets', 'v4', credentials=creds)
        return drive_service, sheets_service
    except Exception as e:
        st.error(f"Failed to authenticate with Google: {e}")
        return None, None

drive_service, sheets_service = get_google_services()

# 2. File Uploader Component for Guests
uploaded_file = st.file_uploader(
    "Choose a photo or video", 
    type=["jpg", "jpeg", "png", "mp4", "mov"]
)

guest_name = st.text_input("Your Name (Optional)")

if uploaded_file is not None:
    if st.button("Upload to Wedding Album"):
        if not drive_service:
            st.error("Google services are not initialized. Check your secrets.")
        else:
            with st.spinner("Uploading your memory safely..."):
                try:
                    from googleapiclient.http import MediaIoBaseUpload
                    import io

                    # Prepare file metadata for Google Drive
                    file_metadata = {
                        'name': f"{guest_name or 'Guest'}_{uploaded_file.name}"
                    }
                    
                    media = MediaIoBaseUpload(
                        io.BytesIO(uploaded_file.getvalue()),
                        mimetype=uploaded_file.type,
                        resumable=True
                    )

                    # Upload directly to Drive (restricted strictly to app-created files)
                    file = drive_service.files().create(
                        body=file_metadata,
                        media_body=media,
                        fields='id, webViewLink'
                    ).execute()

                    st.success("Thank you! Your memory has been successfully uploaded to our wedding album.")
                    
                except Exception as e:
                    st.error(f"An error occurred during upload: {e}")
