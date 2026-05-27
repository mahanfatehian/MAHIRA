# 🧠 Mahira — Intelligent Language Learning App

<p align="center">
  <img src="assets/logo.ico" width="180" alt="Mahira Log">
</p>

<p align="center">
  <b>A smart spaced‑repetition vocabulary trainer built with PySide6.</b><br>
  Learn faster with adaptive review scheduling and machine‑assisted ranking.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11%2B-blue">
  <img src="https://img.shields.io/badge/GUI-PySide6-green">
  <img src="https://img.shields.io/badge/Database-SQLite-orange">
  <img src="https://img.shields.io/badge/ML-scikit--learn-purple">
</p>

---

# 🌍 Supported Languages

Mahira is designed to support multiple languages as the platform grows.  
Currently, the following language is fully implemented:

<img src="https://flagcdn.com/de.svg" width="26"> **German**  A1 (CEFR)


You can add German vocabulary, practice with flashcard‑style review sessions, and progressively strengthen your memory through adaptive learning.


# ✨ Features

### 📚 Vocabulary Management  
- Add words with meaning, gender, and plural  
- Smooth input experience with a built‑in special‑character keyboard  
- Clean interface for organizing your language learning  

### 🔁 Smart Review Sessions  
- Guided, flashcard‑style practice  
- Adaptive scheduling that shows the right words at the right time  
- Difficulty‑rating system to help tailor your learning pace  

### 🧠 Machine‑Assisted Learning  
- A lightweight AI model prioritizes which words you need most  
- Adapts to your strengths and weaknesses over time  

### 📈 Simple Progress Overview  
- Clear review flow  
- Encouragement through visible learning activity  

---


# ⚙️ Installation


```bash
## 1️⃣ Clone the Repository
git clone project_url
cd mahira

## 2️⃣ Create Virtual Environment
python -m venv venv

### Activate:

#### Windows
venv\Scripts\activate

#### Linux / macOS
source venv/bin/activate

## 3️⃣ Install Dependencies
pip install -r requirements.txt

### Example dependencies:
PySide6
SQLAlchemy
numpy
scikit-learn
joblib

## 🚀 Running the Application
cd .\src\
python -m mahira
