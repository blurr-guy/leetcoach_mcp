import sqlite3
from pathlib  import Path
DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok= True)
DB_PATH = DATA_DIR / "leetcode.db"
def connect_database():
    """ Create and return a connection to the SQLite database."""
    conn = sqlite3.connect(DB_PATH)
    return conn

def create_tables():
    conn = connect_database()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS problems(
                   id INTEGER PRIMARY KEY,
                   title TEXT UNIQUE NOT NULL,
                   difficulty TEXT NOT NULL,
                   topic TEXT NOT NULL,
                   companies TEXT,
                   url TEXT NOT NULL)   """)  
                   
    conn.commit()
    conn.close()
    
           
def insert_problem(
        title:str,
        difficulty:str,
        topic: str,
        companies:str,
        url:str
    ):
        conn = connect_database()
        cursor = conn.cursor()
        cursor.execute(""" 
        INSERT OR IGNORE INTO problems (title ,difficulty,topic,companies,url)VALUES (?,?,?,?,?)
                       """, (title,difficulty,topic,companies,url))
        conn.commit()
        conn.close()
def get_all_problems():
    conn = connect_database()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM problems')
    problems= cursor.fetchall()
    conn.close()  
    return problems      
        
    
      
if __name__ =="__main__":
    create_tables()
    insert_problem(
         "Two Sum",
         "Easy",
         "Array",
         "Amazon,Google",
         "https://leetcode.com/problem/two-sum"
    )
    insert_problem(
         "Valid Parentheses",
         "Easy",
         "Stack",
         "Amazon,Meta",
         "https://leetcode.com/problems/valid-parentheses/"
    )
    insert_problem(
         "Merge Intervals",
         "Medium",
         "Array",
         "Google,Microsoft",
         "https://leetcode.com/problems/merge-itervals/"
    )
    

    problems= get_all_problems()
    print("\nLeetcode Problems:\n")
    for problem in problems:
         print(problem)

            


