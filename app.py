from flask import Flask, render_template, request, send_file, redirect, url_for
import os
import threading
from scrape_jobs import run_scraper

app = Flask(__name__)
RESULT_DIR = os.getcwd()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/scrape', methods=['POST'])
def scrape():
    domains = request.form.get('domains').split(',')
    limit = int(request.form.get('limit'))
    
    # Run in separate thread to not block UI
    # For simplicity in this demo, we will block or we need a proper job queue. 
    # Blocking is easiest for MVP so user knows when it's done. 
    # But user asked for "fast".
    # I'll block for now but show a loading state in UI.
    
    result = run_scraper([d.strip() for d in domains], limit)
    
    if result and result.endswith('.xlsx'):
        return redirect(url_for('files'))
    else:
        return f"Error: {result}"

@app.route('/files')
def files():
    files = [f for f in os.listdir(RESULT_DIR) if f.endswith('.xlsx')]
    files.sort(key=lambda x: os.path.getmtime(os.path.join(RESULT_DIR, x)), reverse=True)
    return render_template('files.html', files=files)

@app.route('/download/<filename>')
def download(filename):
    return send_file(os.path.join(RESULT_DIR, filename), as_attachment=True)

if __name__ == '__main__':
    app.run(debug=True, port=5000)
