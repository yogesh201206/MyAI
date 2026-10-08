"""
core/kb_manager.py — Local Knowledge Base management, indexing, and RAG retrieval.

Tables managed in ~/.myai/aizen.db:
  - kb_documents
  - kb_chunks

Responsibilities:
  - Add documents (.pdf, .txt, .md), extract text, chunk, embed, add to FAISS index
  - Detect duplicates and changed files via SHA-256
  - List documents with live status (READY, CHANGED, MISSING, ERROR)
  - Keyword/semantic search (/kb search <query>)
  - Remove documents and cleanup chunks + vector entries
  - Clear entire knowledge base (with confirmation)
  - Build RAG context block for prompt injection when RAG is enabled
"""

import os
import sqlite3
from datetime import datetime

import config
from core.analytics import _db
from core.document_parser import (
    compute_file_hash,
    extract_document_pages,
    chunk_document_pages,
)
from core.embeddings import embed_texts, embed_query, get_model_name
from core.retriever import (
    add_chunks_to_index,
    remove_chunks_from_index,
    clear_index,
    search_index,
    get_total_vectors,
    get_index_size_bytes,
)
from ui.console import console

# ------------------------------------------------------------------
# SCHEMA INITIALIZATION
# ------------------------------------------------------------------

_KB_SCHEMA = """
CREATE TABLE IF NOT EXISTS kb_documents (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    path            TEXT    NOT NULL,
    name            TEXT    NOT NULL,
    file_type       TEXT    NOT NULL,
    file_size       INTEGER NOT NULL,
    file_hash       TEXT    NOT NULL,
    page_count      INTEGER NOT NULL,
    chunk_count     INTEGER NOT NULL,
    added_at        TEXT    NOT NULL,
    last_modified   TEXT    NOT NULL,
    status          TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS kb_chunks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id     INTEGER NOT NULL,
    page_number     INTEGER NOT NULL,
    chunk_index     INTEGER NOT NULL,
    text            TEXT    NOT NULL,
    token_estimate  INTEGER NOT NULL,
    FOREIGN KEY (document_id) REFERENCES kb_documents(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_kbc_doc ON kb_chunks (document_id);
"""


def init_kb_db():
    """Ensure KB tables exist in aizen.db."""
    try:
        with _db() as con:
            con.executescript(_KB_SCHEMA)
            con.commit()
    except Exception:
        pass


# ------------------------------------------------------------------
# HELPERS
# ------------------------------------------------------------------

def _format_size(b: int | None) -> str:
    """Format bytes into readable string."""
    if b is None:
        return "—"
    if b < 1024:
        return f"{b} B"
    elif b < 1024 * 1024:
        return f"{b / 1024:.1f} KB"
    else:
        return f"{b / (1024 * 1024):.2f} MB"


def _get_doc_status(row) -> tuple[str, str]:
    """Check live status of document source on disk."""
    d = dict(row) if hasattr(row, "keys") else row
    path = d.get("path")
    if not path or not os.path.exists(path):
        return "MISSING", "red"

    try:
        current_hash = compute_file_hash(path)
        if current_hash != d.get("file_hash"):
            return "CHANGED", "yellow"
        return "READY", "green"
    except Exception:
        return "ERROR", "red"


# ------------------------------------------------------------------
# ADD DOCUMENT (/kb add <path>)
# ------------------------------------------------------------------

def add_document(path_str: str) -> bool:
    """
    Validate, parse, chunk, embed, and index a document into the Knowledge Base.
    """
    init_kb_db()
    cleaned = (path_str or "").strip().strip("'\"")
    if not cleaned:
        console.print("[yellow]Usage: /kb add <path>[/yellow]")
        return False

    abs_path = os.path.abspath(os.path.expanduser(cleaned))
    if not os.path.exists(abs_path):
        console.print(f"[red]File does not exist: {abs_path}[/red]")
        return False

    if not os.path.isfile(abs_path):
        console.print(f"[red]Not a regular file: {abs_path}[/red]")
        return False

    name = os.path.basename(abs_path)
    _, ext = os.path.splitext(abs_path)
    ext_lower = ext.lower()

    if ext_lower not in (".pdf", ".txt", ".md"):
        console.print(
            f"[red]Unsupported document type '{ext}'.[/red]\n"
            "[dim]Supported: .pdf, .txt, .md[/dim]"
        )
        return False

    file_size = os.path.getsize(abs_path)
    file_hash = compute_file_hash(abs_path)
    last_mod_iso = datetime.fromtimestamp(os.path.getmtime(abs_path)).isoformat()

    # Check for duplicate
    try:
        with _db() as con:
            existing = con.execute(
                "SELECT id, file_hash FROM kb_documents WHERE path = ?", (abs_path,)
            ).fetchone()
            if existing:
                if existing["file_hash"] == file_hash:
                    console.print(
                        f"[yellow]Document already indexed and unchanged: {name}[/yellow]\n"
                        f"[dim]Doc ID: {existing['id']}. Use /kb search <query> to search.[/dim]"
                    )
                    return True
                else:
                    # File changed since indexing — remove old version first
                    remove_document(str(existing["id"]), quiet=True)
    except Exception as e:
        console.print(f"[red]Database error checking existing doc: {e}[/red]")
        return False

    # Extract text with spinner
    with console.status(
        f"[bold cyan]Extracting text from {name}...[/bold cyan]", spinner="dots"
    ):
        pages, err = extract_document_pages(abs_path)

    if err or not pages:
        console.print(f"[red]{err or 'Failed to extract text from document.'}[/red]")
        return False

    # Chunk text
    with console.status(
        f"[bold cyan]Chunking document ({len(pages)} pages)...[/bold cyan]", spinner="dots"
    ):
        chunks = chunk_document_pages(pages)

    if not chunks:
        console.print("[red]No meaningful text chunks could be generated from document.[/red]")
        return False

    # Generate embeddings
    with console.status(
        f"[bold cyan]Generating embeddings for {len(chunks)} chunks...[/bold cyan]", spinner="dots"
    ):
        chunk_texts = [c["text"] for c in chunks]
        try:
            embeddings = embed_texts(chunk_texts)
        except Exception as e:
            console.print(f"[red]Failed generating embeddings: {e}[/red]")
            return False

    # Store in SQLite and FAISS
    with console.status(
        "[bold cyan]Saving index and metadata...[/bold cyan]", spinner="dots"
    ):
        try:
            with _db() as con:
                cur = con.execute(
                    """
                    INSERT INTO kb_documents
                        (path, name, file_type, file_size, file_hash, page_count,
                         chunk_count, added_at, last_modified, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'READY')
                    """,
                    (
                        abs_path,
                        name,
                        ext_lower[1:].upper(),
                        file_size,
                        file_hash,
                        len(pages),
                        len(chunks),
                        datetime.now().isoformat(),
                        last_mod_iso,
                    ),
                )
                doc_id = cur.lastrowid

                chunk_ids = []
                for c in chunks:
                    c_cur = con.execute(
                        """
                        INSERT INTO kb_chunks
                            (document_id, page_number, chunk_index, text, token_estimate)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (doc_id, c["page_number"], c["chunk_index"], c["text"], c["token_estimate"]),
                    )
                    chunk_ids.append(c_cur.lastrowid)

                con.commit()

            # Add to FAISS index
            add_chunks_to_index(chunk_ids, embeddings)

        except Exception as e:
            console.print(f"[red]Error saving to database/index: {e}[/red]")
            return False

    from rich.panel import Panel
    from rich.table import Table

    summary = Table(show_header=False, box=None)
    summary.add_row("Document", f"[bold cyan]{name}[/bold cyan]")
    summary.add_row("ID", str(doc_id))
    summary.add_row("Pages", str(len(pages)))
    summary.add_row("Chunks", str(len(chunks)))
    summary.add_row("Size", _format_size(file_size))
    summary.add_row("Status", "[green]Ready[/green]")

    console.print(
        Panel(summary, title="Knowledge Base Document Added", border_style="green")
    )
    return True


# ------------------------------------------------------------------
# LIST DOCUMENTS (/kb list)
# ------------------------------------------------------------------

def list_documents():
    """Display a Rich table of all indexed Knowledge Base documents."""
    init_kb_db()
    from rich.table import Table

    try:
        with _db() as con:
            rows = con.execute(
                "SELECT * FROM kb_documents ORDER BY id ASC"
            ).fetchall()
    except Exception as e:
        console.print(f"[red]Database error: {e}[/red]")
        return

    if not rows:
        console.print(
            "[yellow]Knowledge Base is empty.[/yellow]\n"
            "[dim]Add a document with [cyan]/kb add <path>[/cyan][/dim]"
        )
        return

    table = Table(title="Knowledge Base Documents")
    table.add_column("ID", style="cyan", justify="right")
    table.add_column("Document", style="bold")
    table.add_column("Type", style="dim")
    table.add_column("Pages", justify="right")
    table.add_column("Chunks", justify="right")
    table.add_column("Size", justify="right")
    table.add_column("Status", justify="left")
    table.add_column("Added", justify="left")

    for r in rows:
        status, color = _get_doc_status(r)
        added_date = r["added_at"][:10] if r["added_at"] else "—"
        table.add_row(
            str(r["id"]),
            r["name"],
            r["file_type"],
            str(r["page_count"]),
            str(r["chunk_count"]),
            _format_size(r["file_size"]),
            f"[{color}]{status}[/{color}]",
            added_date,
        )

    console.print(table)
    console.print(
        "\n[dim]Use [cyan]/kb search <query>[/cyan] to query, "
        "[cyan]/kb remove <id>[/cyan] to delete.[/dim]\n"
    )


# ------------------------------------------------------------------
# SEARCH (/kb search <query>)
# ------------------------------------------------------------------

def search_kb(query_str: str, top_k: int | None = None) -> list[dict]:
    """
    Perform semantic vector retrieval on the Knowledge Base.

    Returns:
        list of chunk result dicts:
        [
            {
                "chunk_id": int,
                "document_id": int,
                "document_name": str,
                "document_path": str,
                "page_number": int,
                "chunk_index": int,
                "text": str,
                "score": float
            }, ...
        ]
    """
    init_kb_db()
    cleaned = (query_str or "").strip()
    if not cleaned:
        return []

    k = top_k or config.rag_top_k
    q_vec = embed_query(cleaned)
    results = search_index(q_vec, top_k=k)
    if not results:
        return []

    chunk_ids = [r[0] for r in results]
    scores_map = {r[0]: r[1] for r in results}

    placeholders = ",".join("?" * len(chunk_ids))
    try:
        with _db() as con:
            rows = con.execute(
                f"""
                SELECT c.id AS chunk_id, c.document_id, c.page_number, c.chunk_index,
                       c.text, d.name AS document_name, d.path AS document_path
                FROM kb_chunks c
                JOIN kb_documents d ON c.document_id = d.id
                WHERE c.id IN ({placeholders})
                """,
                chunk_ids,
            ).fetchall()
    except Exception:
        return []

    output = []
    for row in rows:
        cid = row["chunk_id"]
        output.append({
            "chunk_id": cid,
            "document_id": row["document_id"],
            "document_name": row["document_name"],
            "document_path": row["document_path"],
            "page_number": row["page_number"],
            "chunk_index": row["chunk_index"],
            "text": row["text"],
            "score": scores_map.get(cid, 0.0),
        })

    # Sort descending by similarity score
    output.sort(key=lambda item: item["score"], reverse=True)
    return output


def handle_search_command(argument: str):
    """CLI handler for /kb search <query> [--top N]."""
    parts = (argument or "").strip().split()
    if not parts:
        console.print("[yellow]Usage: /kb search <query> [--top N][/yellow]")
        return

    top_k = config.rag_top_k
    query_words = []
    i = 0
    while i < len(parts):
        if parts[i] in ("--top", "-k") and i + 1 < len(parts):
            try:
                top_k = int(parts[i + 1])
                i += 2
                continue
            except ValueError:
                pass
        query_words.append(parts[i])
        i += 1

    query = " ".join(query_words).strip()
    if not query:
        console.print("[yellow]Usage: /kb search <query>[/yellow]")
        return

    from rich.table import Table

    with console.status("[bold cyan]Searching knowledge base...[/bold cyan]", spinner="dots"):
        hits = search_kb(query, top_k=top_k)

    if not hits:
        console.print("[yellow]No relevant chunks found in Knowledge Base.[/yellow]")
        return

    table = Table(title=f"Knowledge Base Search Results: '{query}'")
    table.add_column("Rank", style="cyan", justify="right")
    table.add_column("Document", style="bold")
    table.add_column("Page", justify="right")
    table.add_column("Score", justify="right")
    table.add_column("Preview", justify="left")

    for rank, hit in enumerate(hits, start=1):
        preview = hit["text"].replace("\n", " ").strip()
        if len(preview) > 90:
            preview = preview[:87] + "..."
        score_val = hit["score"]
        score_color = "green" if score_val >= 0.60 else ("yellow" if score_val >= 0.40 else "dim")

        table.add_row(
            str(rank),
            hit["document_name"],
            f"p.{hit['page_number']}",
            f"[{score_color}]{score_val:.3f}[/{score_color}]",
            preview,
        )

    console.print(table)


# ------------------------------------------------------------------
# REMOVE DOCUMENT (/kb remove <id>)
# ------------------------------------------------------------------

def remove_document(id_str: str, quiet: bool = False) -> bool:
    """
    Remove document metadata, chunks, and FAISS vector index entries for a given doc ID.
    Does NOT delete the source file from disk.
    """
    init_kb_db()
    try:
        doc_id = int(id_str.strip())
    except ValueError:
        if not quiet:
            console.print("[yellow]Usage: /kb remove <id>[/yellow]")
        return False

    try:
        with _db() as con:
            doc = con.execute("SELECT * FROM kb_documents WHERE id = ?", (doc_id,)).fetchone()
            if not doc:
                if not quiet:
                    console.print(f"[red]Document ID {doc_id} not found in Knowledge Base.[/red]")
                return False

            chunk_rows = con.execute(
                "SELECT id FROM kb_chunks WHERE document_id = ?", (doc_id,)
            ).fetchall()
            chunk_ids = [r["id"] for r in chunk_rows]

            # Remove chunks and doc from DB
            con.execute("DELETE FROM kb_chunks WHERE document_id = ?", (doc_id,))
            con.execute("DELETE FROM kb_documents WHERE id = ?", (doc_id,))
            con.commit()

        # Remove from vector index
        remove_chunks_from_index(chunk_ids)

        if not quiet:
            console.print(
                f"[green]✓ Removed Knowledge Base document:[/green] {doc['name']} "
                f"[dim]({len(chunk_ids)} chunks removed)[/dim]"
            )
        return True

    except Exception as e:
        if not quiet:
            console.print(f"[red]Error removing document {doc_id}: {e}[/red]")
        return False


# ------------------------------------------------------------------
# CLEAR KB (/kb clear)
# ------------------------------------------------------------------

def clear_kb(confirmed: bool = False) -> bool:
    """
    Delete all documents, chunks, and reset vector index.
    Does NOT delete source files from disk.
    """
    init_kb_db()
    if not confirmed:
        try:
            from prompt_toolkit import prompt
            answer = prompt("Clear entire AIZEN knowledge base? [y/N]: ").strip().lower()
            if answer not in ("y", "yes"):
                console.print("[yellow]Knowledge Base clear cancelled.[/yellow]")
                return False
        except Exception:
            return False

    try:
        with _db() as con:
            con.execute("DELETE FROM kb_chunks")
            con.execute("DELETE FROM kb_documents")
            con.commit()

        clear_index()
        console.print("[green]✓ Entire Knowledge Base and vector index cleared.[/green]")
        return True
    except Exception as e:
        console.print(f"[red]Error clearing knowledge base: {e}[/red]")
        return False


# ------------------------------------------------------------------
# STATUS (/kb status)
# ------------------------------------------------------------------

def get_kb_counts() -> tuple[int, int]:
    """Return (doc_count, chunk_count) safely."""
    init_kb_db()
    try:
        with _db() as con:
            d_count = con.execute("SELECT COUNT(*) FROM kb_documents").fetchone()[0]
            c_count = con.execute("SELECT COUNT(*) FROM kb_chunks").fetchone()[0]
        return d_count, c_count
    except Exception:
        return 0, 0


def show_kb_status():
    """Render Rich panel with Knowledge Base status and diagnostics."""
    from rich.panel import Panel
    from rich.table import Table

    d_count, c_count = get_kb_counts()
    index_size = get_index_size_bytes()
    rag_state = "[green]ON[/green]" if config.rag_enabled else "[yellow]OFF[/yellow]"

    table = Table(show_header=False, box=None)
    table.add_row("Documents", str(d_count))
    table.add_row("Chunks", f"{c_count:,}")
    table.add_row("Vector Backend", "FAISS (IndexIDMap / IndexFlatIP)")
    table.add_row("Vector Dimension", "384")
    table.add_row("Vectors in Index", f"{get_total_vectors():,}")
    table.add_row("Embedding Model", get_model_name())
    table.add_row("Index File Size", _format_size(index_size))
    table.add_row("RAG Automatic Retrieval", rag_state)
    table.add_row("RAG Top-K", str(config.rag_top_k))
    table.add_row("RAG Similarity Threshold", f"{config.rag_similarity_threshold:.2f}")
    table.add_row("RAG Max Context Tokens", str(config.rag_max_context_tokens))

    console.print(Panel(table, title="Knowledge Base & RAG Status", border_style="cyan"))


# ------------------------------------------------------------------
# AUTOMATIC RAG CONTEXT BUILDER
# ------------------------------------------------------------------

def build_rag_context(prompt: str) -> tuple[str | None, list[dict]]:
    """
    When RAG is enabled, retrieve relevant chunks for the user prompt,
    enforce relevance threshold, token budget, and format the context block.

    Returns:
        (rag_context_text: str | None, used_sources: list[dict])
    """
    if not config.rag_enabled:
        return None, []

    d_count, _ = get_kb_counts()
    if d_count == 0:
        return None, []

    hits = search_kb(prompt, top_k=config.rag_top_k)
    if not hits:
        return None, []

    # Filter by similarity threshold
    threshold = config.rag_similarity_threshold
    relevant_hits = [h for h in hits if h["score"] >= threshold]
    if not relevant_hits:
        return None, []

    # Enforce token budget for RAG context
    max_tokens = config.rag_max_context_tokens
    accumulated_tokens = 0
    selected_hits = []

    for hit in relevant_hits:
        chunk_tokens = max(1, len(hit["text"]) // 4)
        if accumulated_tokens + chunk_tokens > max_tokens and selected_hits:
            break
        selected_hits.append(hit)
        accumulated_tokens += chunk_tokens

    if not selected_hits:
        return None, []

    # Format context block
    sections = []
    for h in selected_hits:
        doc_name = h["document_name"]
        page = h["page_number"]
        chunk_idx = h["chunk_index"]
        text = h["text"].strip()
        sections.append(
            f"Source: {doc_name}\n"
            f"Page: {page}\n"
            f"Chunk: {chunk_idx}\n\n"
            f"{text}"
        )

    header = (
        "[KNOWLEDGE BASE CONTEXT]\n\n"
        "Use the supplied knowledge-base context when relevant.\n"
        "Do not claim unsupported details are present in the sources.\n"
        "If the context is insufficient, state so clearly.\n"
        "Cite sources using the format [DocumentName, p.X] or [Source: DocumentName, page X]."
    )
    footer = "[END KNOWLEDGE BASE CONTEXT]"

    rag_text = f"{header}\n\n" + "\n\n---\n\n".join(sections) + f"\n\n{footer}"
    return rag_text, selected_hits
