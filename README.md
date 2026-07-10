# 🤖 LeetCoach MCP

An AI-powered LeetCode coaching server built using the **Model Context Protocol (MCP)**. The goal of this project is to enable AI assistants to recommend coding problems, track progress, analyze performance, and generate personalized interview preparation plans.

## 🚀 Tech Stack

* Python
* Model Context Protocol (MCP)
* Git & GitHub

## 📅 Project Progress

### ✅ Day 1

* Learned the fundamentals of the Model Context Protocol (MCP).
* Understood the roles of MCP Client, MCP Server, Tools, and Resources.
* Set up the project structure and Python virtual environment.
* Installed the official MCP Python SDK.
* Built and ran my first MCP server.
* Created three MCP tools:

  * `hello()`
  * `add()`
  * `multiply()`
* Initialized the project with Git.

## 🎯 Upcoming Features

* Connect the MCP server to Claude Desktop.
* Design the LeetCoach architecture.
* Add problem recommendation tools.
* Track solved LeetCode problems.
* Generate AI-powered study plans.
* Build analytics for coding progress.

## 📌 Learning Goal

This project is part of my journey to learn AI application development, backend engineering, and the Model Context Protocol by building a real-world, portfolio-ready project.
# Day 2 – SQLite Database Integration

## 🚀 Progress Update

Today, I added persistent data storage to the LeetCode Coach MCP project by integrating an SQLite database.

### ✅ Features Implemented

* Created a local **SQLite** database (`leetcode.db`)
* Established a database connection using Python's built-in `sqlite3` module
* Created a `problems` table to store LeetCode problem information
* Implemented CRUD operations:

  * **Create** – Insert new problems into the database
  * **Read** – Retrieve stored problems
  * **Update** – Modify existing problem records
  * **Delete** – Remove problems from the database
* Verified that data is successfully stored and retrieved

### 🛠️ Technologies Used

* Python
* SQLite
* sqlite3

### 📁 Files Added

```text
database.py
data/
└── leetcode.db
```

### 📚 What I Learned

* How SQLite stores data in a lightweight database file
* Creating tables using SQL
* Writing SQL queries from Python
* Implementing CRUD operations
* Managing database connections and transactions

### 🎯 Next Goal

Connect the database with the MCP server so that AI assistants can access, search, and manage LeetCode problems dynamically.
