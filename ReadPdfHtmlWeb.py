from flask import Flask, request, jsonify
import fitz  # PyMuPDF
from googletrans import Translator
import pyttsx3
import requests
from io import BytesIO
import nltk
import re
from bs4 import BeautifulSoup
import threading

nltk.download('punkt')
from nltk.tokenize import sent_tokenize

app = Flask(__name__)
reading_thread = None
stop_reading_event = threading.Event()

class ContentProcessor:
    def __init__(self, url, content_type, content_language, start_page=1):
        self.url = url
        self.content_type = content_type
        self.content_language = content_language
        self.text = ""
        self.translated_text = ""
        self.start_page = start_page

    def download_pdf(self):
        response = requests.get(self.url)
        if response.status_code == 200:
            return BytesIO(response.content)
        else:
            response.raise_for_status()

    def extract_text_from_pdf(self, pdf_file):
        pdf_document = fitz.open("pdf", pdf_file)
        for page_num in range(self.start_page-1, len(pdf_document)):
            page = pdf_document.load_page(page_num)
            self.text += f'página: {page_num}.\n{page.get_text()}'
        return self.text

    def extract_text_from_html(self):
        response = requests.get(self.url)
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'html.parser')
            paragraphs = soup.find_all('p')
            self.text = ' '.join([p.get_text() for p in paragraphs])
        else:
            response.raise_for_status()
        return self.text

    def clean_text(self, text):
        # Eliminar caracteres no imprimibles solo si el idioma no es español
        if self.content_language != 'es':
            text = re.sub(r'[^\x00-\x7F]+', ' ', text)
            text = re.sub(r'[\x00-\x1F]+', ' ', text)
        # Reemplazar saltos de línea dentro de los párrafos con espacios
        text = re.sub(r'\n+', ' ', text)
        # Eliminar espacios repetidos
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    def translate_and_read_sentence(self, sentence, dest_language='es'):
        translator = Translator()
        engine = pyttsx3.init()
        engine.setProperty('rate', 150)  # Ajustar la velocidad de lectura

        try:
            if dest_language != 'es':
                translation = translator.translate(sentence, src=self.content_language, dest=dest_language)
                translated_sentence = translation.text
            else:
                translated_sentence = sentence
            
        except Exception as e:
            print(f"Error translating sentence: '{sentence}': {e}")
            translated_sentence = f"[Error translating sentence: {sentence}]"

        if stop_reading_event.is_set():
            return translated_sentence

        print(f"Reading: {translated_sentence}")
        engine.say(translated_sentence)
        engine.runAndWait()

        return translated_sentence

    def process_content(self, dest_language='es'):
        if self.content_type == 'pdf':
            pdf_file = self.download_pdf()
            self.extract_text_from_pdf(pdf_file)
            self.text = self.clean_text(self.text)
            sentences = sent_tokenize(self.text)
        elif self.content_type == 'html':
            self.extract_text_from_html()
            self.text = self.clean_text(self.text)
            sentences = sent_tokenize(self.text)

        if self.content_language == 'es':
            # Si el idioma es español, solo leer
            for sentence in sentences:
                if stop_reading_event.is_set():
                    break
                self.translate_and_read_sentence(sentence, dest_language)
            self.translated_text = self.text
        else:
            # Si el idioma no es español, traducir y leer
            translated_chunks = []
            for sentence in sentences:
                if stop_reading_event.is_set():
                    break
                translated_sentence = self.translate_and_read_sentence(sentence, dest_language)
                translated_chunks.append(translated_sentence)
            self.translated_text = ' '.join(translated_chunks)

        return self.text, self.translated_text

def background_processing(url, content_type, content_language, dest_language, start_page):
    global stop_reading_event
    stop_reading_event.clear()
    processor = ContentProcessor(url, content_type, content_language, start_page=start_page)
    return processor.process_content(dest_language)

@app.route('/process_content', methods=['POST'])
def process_content():
    global reading_thread
    if reading_thread is not None and reading_thread.is_alive():
        return jsonify({'error': 'Reading is already in progress'}), 400

    data = request.get_json()
    url = data.get('url')
    content_type = data.get('content_type')
    content_language = data.get('content_language')  # Se recibe el idioma desde la aplicación
    dest_language = data.get('dest_language', 'es')
    start_page = data.get('start_page', 1)  # Se recibe la página inicial, por defecto es 1
    
    if not url or not content_type or not content_language:
        return jsonify({'error': 'URL, content type, and content language are required'}), 400

    reading_thread = threading.Thread(target=background_processing, args=(url, content_type, content_language, dest_language, start_page))
    reading_thread.start()
    
    original_text, translated_text = background_processing(url, content_type, content_language, dest_language, start_page)

    return jsonify({
        'original_text': original_text,
        'translated_text': translated_text
    })


@app.route('/status', methods=['GET'])
def status():
    return jsonify({"status": "running"}), 200


@app.route('/stop_reading', methods=['POST'])
def stop_reading():
    global stop_reading_event
    stop_reading_event.set()
    return jsonify({'message': 'Reading stopped'})

if __name__ == '__main__':
    # Ejecutar la API Flask
    app.run(host='0.0.0.0', port=49201)
