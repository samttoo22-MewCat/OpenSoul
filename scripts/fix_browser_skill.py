import subprocess
import sys

def fix_browser_skill():
    print("--- 🔧 正在修復 Browser Skill (docker 內補丁) ---")
    
    container_name = "openclaw-openclaw-cli-1"
    
    # 1. 更新 apt 並安裝所需的系統套件 (ffmpeg 等)
    print(f"正在 {container_name} 內安裝系統依賴 (ffmpeg, pip)...")
    try:
        subprocess.run([
            "docker", "exec", "-u", "root", container_name,
            "bash", "-c", "apt-get update && apt-get install -y ffmpeg python3-pip"
        ], check=True)
        print("✅ 系統依賴安裝完成")
    except Exception as e:
        print(f"⚠️ 系統依賴安裝失敗 (可能已安裝或容器名不對): {e}")

    # 2. 安裝 seleniumbase
    print(f"正在 {container_name} 內安裝 seleniumbase...")
    try:
        subprocess.run([
            "docker", "exec", "-u", "root", container_name,
            "pip", "install", "seleniumbase", "--break-system-packages"
        ], check=True)
        print("✅ seleniumbase 安裝完成")
    except Exception as e:
        print(f"❌ seleniumbase 安裝失敗: {e}")
        return

    # 3. 安裝瀏覽器驅動 (uc_gui 需要)
    print(f"正在 {container_name} 內安裝瀏覽器驅動...")
    try:
        subprocess.run([
            "docker", "exec", "-u", "root", container_name,
            "sbase", "install", "chromedriver"
        ], check=True)
        print("✅ 瀏覽器驅動安裝完成")
    except Exception as e:
        print(f"⚠️ 瀏覽器驅動安裝警告 (可能已存在): {e}")

    print("\n🎉 Browser Skill 修復腳本執行完畢！")
    print("提示：這是一個熱修復補丁。若重啟容器可能需要重新執行，直到下一次 Dockerfile 重新 Build 為止。")

if __name__ == "__main__":
    fix_browser_skill()
