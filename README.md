1. Tesseract OCR 설치
2. exe 파일 우클릭 → 관리자 권한 실행
3. Ctrl + Shift + T 누른 후 영역 선택

python -m PyInstaller --onefile --noconsole --clean --collect-all pywin32 --name OCRTranslator ocr_translator.py
exe 파일로 변환
