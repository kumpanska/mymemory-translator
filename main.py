import os
import requests
import psycopg2
from psycopg2 import OperationalError, Error
from dotenv import load_dotenv

load_dotenv()

API_BASE_URL = os.getenv("API_BASE_URL")
API_EMAIL = os.getenv("API_EMAIL")

DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT")
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")

TARGET_LANGUAGES = {
    "1": ("uk", "Ukrainian"),
    "2": ("es", "Spanish"),
    "3": ("de", "German"),
}


def get_connection():
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        connect_timeout=5,
    )


def init_db(conn) -> None:
    with conn.cursor() as cursor:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS languages (
                id SERIAL PRIMARY KEY,
                code VARCHAR(10) NOT NULL UNIQUE,
                name VARCHAR(50) NOT NULL
            );
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS translations (
                id SERIAL PRIMARY KEY,
                language_id INTEGER NOT NULL REFERENCES languages(id) ON DELETE CASCADE,
                source_text TEXT NOT NULL,
                translated_text TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (language_id, source_text)
            );
        """)
    conn.commit()


def translate_text(text: str, target_lang_code: str) -> str | None:
    if not API_BASE_URL:
        print("[Config Error] API_BASE_URL is not set in the .env file.")
        return None

    params = {
        "q": text,
        "langpair": f"en|{target_lang_code}",
    }
    if API_EMAIL:
        params["de"] = API_EMAIL

    try:
        response = requests.get(API_BASE_URL, params=params, timeout=10)

        if response.status_code != 200:
            print(f"[API Error] Server returned status {response.status_code}")
            return None

        if not response.text.strip():
            print("[API Error] Received an empty response from the server.")
            return None

        data = response.json()
        if not data or "responseData" not in data:
            print("[API Error] Response does not contain responseData.")
            return None

        # Internal MyMemory API status
        api_status = data.get("responseStatus")
        if api_status != 200:
            print(f"[MyMemory API Error] Code {api_status}: {data.get('responseDetails')}")
            return None

        translated = data["responseData"].get("translatedText")
        if not translated or not translated.strip():
            print("[API Error] Received an empty translation.")
            return None

        return translated.strip()

    except requests.exceptions.ConnectionError:
        print("[Network Error] No network connection or server is unreachable.")
    except requests.exceptions.Timeout:
        print("[Network Error] Request timed out.")
    except requests.exceptions.RequestException as err:
        print(f"[Request Error] {err}")
    except ValueError:
        print("[Data Error] Failed to parse JSON from the response.")

    return None


def save_to_db(conn, lang_code: str, lang_name: str, source_text: str, translated_text: str) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO languages (code, name)
            VALUES (%s, %s)
            ON CONFLICT (code) DO NOTHING;
            """,
            (lang_code, lang_name),
        )

        cursor.execute("SELECT id FROM languages WHERE code = %s;", (lang_code,))
        language_id = cursor.fetchone()[0]

        cursor.execute(
            """
            INSERT INTO translations (language_id, source_text, translated_text)
            VALUES (%s, %s, %s)
            ON CONFLICT (language_id, source_text) DO NOTHING;
            """,
            (language_id, source_text, translated_text),
        )
        is_inserted = cursor.rowcount > 0

    conn.commit()

    if is_inserted:
        print("[DB] Translation successfully saved to PostgreSQL.")
    else:
        print("[DB] Translation already exists — duplicate not created.")


def display_from_db(conn) -> None:
    with conn.cursor() as cursor:
        cursor.execute("""
            SELECT l.name, l.code, t.source_text, t.translated_text
            FROM translations t
            JOIN languages l ON t.language_id = l.id
            ORDER BY t.id DESC;
        """)
        rows = cursor.fetchall()

    print("\nSaved translations from PostgreSQL")
    if not rows:
        print("No records found.")
        return

    print(f"{'Language':<12} | {'Code':<4} | {'Original (EN)':<22} | {'Translation'}")
    print("-" * 68)
    for lang_name, code, src, tr in rows:
        print(f"{lang_name:<12} | {code:<4} | {src:<22} | {tr}")


def main() -> None:
    text = input("Enter English text to translate (e.g., Hello world): ").strip()
    if not text:
        print("Text cannot be empty.")
        return

    print("\nSelect target language (langpair parameter):")
    for key, (code, name) in TARGET_LANGUAGES.items():
        print(f"  {key}. {name} (en|{code})")

    choice = input("Your choice (1-3): ").strip()
    if choice not in TARGET_LANGUAGES:
        print("Invalid choice.")
        return

    lang_code, lang_name = TARGET_LANGUAGES[choice]
    translated = translate_text(text, lang_code)
    if translated is None:
        return

    print("\nMyMemory API Response")
    print(f"Original (EN):  {text}")
    print(f"Language ({lang_code}):  {translated}")

    try:
        with get_connection() as conn:
            init_db(conn)
            save_to_db(conn, lang_code, lang_name, text, translated)
            display_from_db(conn)
    except OperationalError as err:
        print(f"[DB Error] Failed to connect to PostgreSQL: {err}")
    except Error as err:
        print(f"[DB Error] SQL error: {err}")


if __name__ == "__main__":
    main()