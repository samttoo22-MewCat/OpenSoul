import argparse
import subprocess
import os
import sys

def main():
    parser = argparse.ArgumentParser(description="Summarize web pages and YouTube links.")
    parser.add_argument("--url", type=str, required=True, help="The URL to summarize (web page or YouTube link)")
    parser.add_argument("--length", type=str, choices=["short", "medium", "long", "xl", "xxl"], default="xl", help="Summary length")
    parser.add_argument("--extract-only", type=str, choices=["true", "false"], default="false", help="Extract text without summarizing (true/false)")
    parser.add_argument("--format", type=str, choices=["text", "md"], default="text", help="Output format")
    args = parser.parse_args()

    cmd = ["docker", "exec"]
    
    # Passes environment configuration to docker exec
    if "NODE_TLS_REJECT_UNAUTHORIZED" in os.environ:
        cmd.extend(["-e", f"NODE_TLS_REJECT_UNAUTHORIZED={os.environ['NODE_TLS_REJECT_UNAUTHORIZED']}"])
    if "SUMMARIZE_MODEL" in os.environ:
        cmd.extend(["-e", f"SUMMARIZE_MODEL={os.environ['SUMMARIZE_MODEL']}"])
        
    cmd.extend(["openclaw-openclaw-gateway-1", "summarize", args.url])
    
    # Flags mapping
    if args.length != "xl":
        cmd.extend(["--length", args.length])
    if args.format != "text":
        cmd.extend(["--format", args.format])
    if args.extract_only.lower() == "true":
        cmd.append("--extract")
        
    # Prevent MSYS path conversion on Windows
    env = os.environ.copy()
    env["MSYS_NO_PATHCONV"] = "1"
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", check=True, env=env)
        print(result.stdout)
    except subprocess.CalledProcessError as e:
        print(f"Error executing summarize: {e.stderr}\n\nSTDOUT: {e.stdout}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
