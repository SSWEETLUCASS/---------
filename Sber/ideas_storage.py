import os

IDEAS_FILE = "ideas.txt"

def load_ideas() -> list[str]:
    """Загружает все идеи из файла"""
    if not os.path.exists(IDEAS_FILE):
        return []
    with open(IDEAS_FILE, "r", encoding="utf-8") as f:
        return [line.strip() for line in f.readlines() if line.strip()]

def save_idea(idea: str):
    """Сохраняет новую идею, если она ещё не сохранена"""
    ideas = load_ideas()
    if idea not in ideas:
        with open(IDEAS_FILE, "a", encoding="utf-8") as f:
            f.write(idea + "\n")
