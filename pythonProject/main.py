# main.py
import sys

def main():
    if "--web" in sys.argv:
        import subprocess
        subprocess.run(["streamlit", "run", "web_app.py"])
    elif "--bridge" in sys.argv:
        import uvicorn
        uvicorn.run("agent_bridge:app", host="0.0.0.0", port=8765)
    else:
        from tui import AgentTUI
        AgentTUI().run()

if __name__ == "__main__":
    main()