"""Seed exclusively fictional data into a fresh LOCAL database. NEVER run in production."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.db import database, init_db  # noqa: E402
from app.security import make_password_hash  # noqa: E402


def seed(path: str) -> bool:
    init_db(path)
    password = make_password_hash("DemoPass2026!")
    with database(path) as db:
        if db.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
            print("Database already contains users; demo seed skipped.")
            return False
        accounts = [
            ("admin@demo.example", "Администратор", "admin", "", None),
            ("company@demo.example", "Мария Тестовая", "employer", "", None),
            ("kladovshik@demo.example", "Александр Демонстрационный", "candidate", "+70000000001", ("Кладовщик", "Подольск", "1С, инвентаризация, склад", 65000, "Сменный", "Полная")),
            ("buhgalter@demo.example", "Наталья Демонстрационная", "candidate", "+70000000002", ("Бухгалтер", "Москва", "1С, бухгалтерия, Excel", 90000, "Полный день", "Полная")),
            ("inzhen@demo.example", "Сергей Демонстрационный", "candidate", "+70000000003", ("Инженер", "Москва", "автоматизация, диагностика, Excel", 110000, "Полный день", "Полная")),
            ("manager@demo.example", "Ольга Демонстрационная", "candidate", "+70000000004", ("Менеджер по продажам", "Удалённо", "переговоры, CRM, продажи", 85000, "Удалённо", "Полная")),
        ]
        ids = {}
        for email, name, role, phone, profile in accounts:
            uid = db.execute("INSERT INTO users(email,name,role,phone,password_hash) VALUES(?,?,?,?,?)", (email, name, role, phone, password)).lastrowid
            ids[role if role != 'candidate' else email] = uid
            if profile:
                db.execute(
                    """INSERT INTO candidate_profiles(user_id,profession,city,skills,salary_min,schedule,employment)
                    VALUES(?,?,?,?,?,?,?)""", (uid, *profile),
                )
        db.execute("INSERT INTO employer_profiles(user_id,company_name,verified) VALUES(?,?,1)", (ids['employer'], "Компания «Пример»"))
        jobs = [
            ("Кладовщик", "Подольск", 70000, 95000, "Сменный", "Полная", "1С, склад", "Складской учёт, отгрузка, график 2/2. Тестовая вакансия."),
            ("Бухгалтер", "Москва", 90000, 130000, "Полный день", "Полная", "1С, Excel", "Первичная документация и учёт. Тестовая вакансия."),
            ("Инженер по эксплуатации", "Москва", 110000, 160000, "Полный день", "Полная", "диагностика, Excel", "Поддержка и диагностика оборудования. Тестовая вакансия."),
            ("Менеджер по продажам", "Удалённо", 85000, 140000, "Удалённо", "Полная", "CRM, переговоры", "B2B-продажи по всей России. Тестовая вакансия."),
        ]
        for title, city, lo, hi, schedule, employment, skills, description in jobs:
            db.execute(
                """INSERT INTO vacancies(employer_id,title,city,salary_min,salary_max,schedule,employment,skills,description)
                VALUES(?,?,?,?,?,?,?,?,?)""", (ids['employer'], title, city, lo, hi, schedule, employment, skills, description),
            )
    print(f"Created 6 fictional accounts and 4 demo vacancies in {path}")
    print("Demo password for all accounts: DemoPass2026!")
    print("Employer: company@demo.example; Candidate: kladovshik@demo.example; Admin: admin@demo.example")
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed demonstration users in an empty local database")
    parser.add_argument("--db", default=os.getenv("OPYT50_DB_PATH", str(ROOT / 'data' / 'opyt50.db')))
    args = parser.parse_args()
    seed(args.db)
