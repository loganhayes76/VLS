import base64
import requests
import pandas as pd
import io
import streamlit as st

class GitHub_Sync:
    def __init__(self, branch="main"):
        # Pulls securely from your .streamlit/secrets.toml file
        try:
            self.token = st.secrets["GITHUB_PAT"]
            self.repo = st.secrets["GITHUB_REPO"]
        except:
            st.error("⚠️ GitHub PAT or Repo Name missing from .streamlit/secrets.toml")
            self.token = ""
            self.repo = ""
            
        self.branch = branch
        self.headers = {
            "Authorization": f"token {self.token}",
            "Accept": "application/vnd.github.v3+json"
        }
        self.base_url = f"https://api.github.com/repos/{self.repo}/contents"

    def push_slate(self, df, sport_name):
        """Converts a DataFrame to CSV and pushes it to GitHub."""
        if not self.token: return False
        
        file_path = f"active_slates/{sport_name}_slate.csv"
        url = f"{self.base_url}/{file_path}"
        
        csv_data = df.to_csv(index=False)
        encoded_content = base64.b64encode(csv_data.encode("utf-8")).decode("utf-8")
        
        # Check if file exists to get the SHA (required to update existing files)
        sha = None
        get_resp = requests.get(url, headers=self.headers)
        if get_resp.status_code == 200:
            sha = get_resp.json().get("sha")
            
        payload = {
            "message": f"Auto-sync {sport_name} slate via VLS 3000",
            "content": encoded_content,
            "branch": self.branch
        }
        if sha: 
            payload["sha"] = sha
            
        put_resp = requests.put(url, headers=self.headers, json=payload)
        return put_resp.status_code in [200, 201]

    def pull_slate(self, sport_name):
        """Pulls a CSV from GitHub and returns a DataFrame."""
        if not self.token: return None
        
        file_path = f"active_slates/{sport_name}_slate.csv"
        url = f"{self.base_url}/{file_path}?ref={self.branch}"
        
        resp = requests.get(url, headers=self.headers)
        if resp.status_code == 200:
            content_b64 = resp.json().get("content", "")
            csv_string = base64.b64decode(content_b64).decode("utf-8")
            return pd.read_csv(io.StringIO(csv_string))
        return None
    