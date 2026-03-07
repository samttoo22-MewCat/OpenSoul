#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/soul_note_api.py

Soul Note Web API 服務 - 為 HTML 面板提供後端支持。

啟動：
  python scripts/soul_note_api.py
  # 訪問 http://localhost:5000

或在 .claude/launch.json 中配置作為開發伺服器。
"""

import sys
import io
from pathlib import Path
from datetime import datetime
import json

# 強制 UTF-8 輸出
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# 加入 openSOUL 到路徑
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from soul.core.soul_note import get_soul_note_manager

try:
    from flask import Flask, request, jsonify, send_from_directory
except ImportError:
    print("❌ Flask 未安裝。安裝：pip install flask")
    sys.exit(1)

app = Flask(__name__)
app.config['JSON_ENSURE_ASCII'] = False

manager = get_soul_note_manager()


@app.route('/')
def index():
    """提供 HTML 面板。"""
    return send_from_directory(Path(PROJECT_ROOT) / 'soul', 'soul_note_web.html')


@app.route('/api/soul-note/add', methods=['POST'])
def api_add_note():
    """添加筆記。"""
    try:
        data = request.json
        content = data.get('content', '').strip()
        category = data.get('category', 'reflection')
        tags = data.get('tags', [])

        if not content:
            return jsonify({'error': '內容不能為空'}), 400

        timestamp = manager.add_note(
            content=content,
            category=category,
            tags=tags
        )

        return jsonify({
            'success': True,
            'timestamp': timestamp,
            'message': '筆記已添加'
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/soul-note/list', methods=['GET'])
def api_list_notes():
    """列出筆記。"""
    try:
        filter_type = request.args.get('filter', 'today')

        if filter_type == 'today':
            notes = manager.get_notes_today()
        elif filter_type == 'all':
            notes = manager.get_all_notes()
        else:
            notes = manager.get_notes_by_category(filter_type)

        # 按時間戳倒序排列
        notes.sort(key=lambda x: x['timestamp'], reverse=True)

        return jsonify({
            'notes': notes,
            'count': len(notes)
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/soul-note/compress', methods=['POST'])
def api_compress():
    """壓縮今日筆記。"""
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        timestamp = manager.compress_daily_reflection(today, merge_existing=True)

        if timestamp:
            return jsonify({
                'success': True,
                'timestamp': timestamp,
                'message': '壓縮完成'
            })
        else:
            return jsonify({
                'success': False,
                'message': '沒有筆記可壓縮'
            }), 400

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/soul-note/reflections', methods=['GET'])
def api_reflections():
    """列出所有反思。"""
    try:
        reflections = manager.get_all_reflections()

        # 按日期倒序排列
        reflections.sort(key=lambda x: x['date'], reverse=True)

        return jsonify({
            'reflections': reflections,
            'count': len(reflections)
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/soul-note/export', methods=['GET'])
def api_export():
    """導出筆記。"""
    try:
        content = manager.export_for_llm()

        return jsonify({
            'content': content,
            'timestamp': datetime.now().isoformat()
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/soul-note/stats', methods=['GET'])
def api_stats():
    """獲取統計信息。"""
    try:
        all_notes = manager.get_all_notes()
        today_notes = manager.get_notes_today()
        reflections = manager.get_all_reflections()

        return jsonify({
            'total_notes': len(all_notes),
            'today_notes': len(today_notes),
            'reflections': len(reflections),
            'auto_compress_interval': manager.auto_compress_interval // 60  # 轉換為分鐘
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/soul-note/health', methods=['GET'])
def health_check():
    """健康檢查。"""
    return jsonify({
        'status': 'ok',
        'timestamp': datetime.now().isoformat()
    })


@app.errorhandler(404)
def not_found(e):
    """處理 404 錯誤。"""
    return jsonify({'error': 'Not found'}), 404


@app.errorhandler(500)
def internal_error(e):
    """處理 500 錯誤。"""
    return jsonify({'error': 'Internal server error'}), 500


def main():
    """啟動伺服器。"""
    import argparse

    parser = argparse.ArgumentParser(description='Soul Note API 伺服器')
    parser.add_argument('--host', default='127.0.0.1', help='伺服器主機')
    parser.add_argument('--port', type=int, default=5000, help='伺服器埠號')
    parser.add_argument('--debug', action='store_true', help='調試模式')

    args = parser.parse_args()

    print("=" * 60)
    print("Soul Note API 伺服器")
    print("=" * 60)
    print(f"\n🌐 Web 面板: http://{args.host}:{args.port}")
    print(f"📡 API 端點: http://{args.host}:{args.port}/api/soul-note/*\n")

    app.run(
        host=args.host,
        port=args.port,
        debug=args.debug,
        use_reloader=False
    )


if __name__ == '__main__':
    main()
