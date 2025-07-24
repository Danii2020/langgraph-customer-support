# LangGraph Automatic Customer Support Workflow

An automated email support pipeline that uses LangGraph and Gmail API to fetch and classify incoming customer emails.
This repository covers the **first two nodes** of the graph:

1. **Load Latest Email** (Gmail API)
2. **Classify Email** (GPT‑4o‑mini into: `product_inquiry`, `customer_complaint`, `customer_feedback`, `unrelated`)

---

## 🚀 Features

* **Node 1:** Connects to Gmail, retrieves the most recent unread email
* **Node 2:** Uses OpenAI’s GPT‑4o‑mini to classify the email into one of four support categories

---

## 🧰 Prerequisites

* Python 3.9+
* A Gmail API OAuth credential (`credentials.json`)
* OpenAI API key
* [UV](https://github.com/astral-sh/uv) (for `uv pip` commands)

---

## ⚙️ Installation

1. **Clone the repo**

   ```bash
   git clone https://github.com/Danii2020/langgraph-customer-support.git
   cd langgraph-customer-support
   ```

2. **Create & activate a virtual environment**

   ```bash
   uv venv
   source .venv/bin/activate
   ```

3. **Install dependencies**

   ```bash
   uv pip install -r requirements.txt
   ```

4. **Configure environment**

   * Copy the example:

     ```bash
     cp .env.example .env
     ```
   * Edit `.env` and set your OpenAI API key:

     ```
     OPENAI_API_KEY=sk-...
     ```

5. **Prepare Gmail credentials**
   Place your `credentials.json` (OAuth client secret) file in the root of the directory `credentials.json`.

---

## 📝 Usage

Once installed and configured:

```bash
python main.py
```

The graph will:

1. Poll Gmail for your latest unread email.
2. Pass the email’s subject & body into GPT‑4o‑mini.
3. Output email body and its category.

---

## 🔜 Next Steps

* **Node 3**: Generate a tailored reply (with RAG for certain categories)
* **Node 4**: Send the crafted response via Gmail API
* Add retries, logging, and monitoring for production readiness

---

## 📖 References

Watch the YouTube video of this project for a more detailed explanation here: https://youtu.be/R4Lwz2ChKGQ

---

**Enjoy building your automated customer support workflow!** 🚀
