import fitz
import pdfplumber
from langchain_text_splitters import RecursiveCharacterTextSplitter


def extract_chunks_from_pdf(source_id, source_name, temp_path):
    """Extract text + tables per page, merge in order."""
    batch = []

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=768,       
        chunk_overlap=150,    
        separators=[
            "\n\n",   
            "\n",
            ". ",     
            ""
        ]
    )

    # Open both readers on the same file
    fitz_doc = fitz.open(temp_path)
    
    with pdfplumber.open(temp_path) as plumber_doc:
        for page_num in range(len(fitz_doc)):
            fitz_page    = fitz_doc[page_num]
            plumber_page = plumber_doc.pages[page_num]
            current_section = "unknown"

            # Extract tables via pdfplumber
            tables = plumber_page.extract_tables()
            table_texts = []
            for table in tables:
                if not table:
                    continue
                # Convert table rows to readable text
                rows = []
                for row in table:
                    clean_row = [cell.strip() if cell else "" for cell in row]
                    rows.append(" | ".join(clean_row))
                table_text = "\n".join(rows)
                table_texts.append(table_text)

            # --- 2. Extract text blocks via PyMuPDF ---
            text_blocks = []

            for block in fitz_page.get_text("dict")["blocks"]:
                if "lines" not in block:
                    continue

                block_text = ""
                for line in block["lines"]:
                    for span in line["spans"]:
                        # Detect headings by font size
                        if span["size"] > 14 and span["text"].strip():
                            current_section = span["text"].strip()
                        block_text += span["text"]

                block_text = block_text.strip()
                if block_text:
                    text_blocks.append(block_text)

            # --- 3. Combine: text + tables for this page ---
            page_content_parts = text_blocks + table_texts
            full_page_text = "\n\n".join(page_content_parts)

            if not full_page_text.strip():
                continue

            # this creates chunks from per page content and attach metadata
            chunks = splitter.create_documents(
                [full_page_text],
                metadatas=[{                    
                    "source_id"   : source_id,        
                    "source_name" :   source_name,                   
                    "source_type"   : "pdf",               
                    "page"        : page_num + 1,          
                    "section"     : current_section,
                }]
            )
            batch.extend(chunks)

            if len(batch) >= 100:
                yield batch[:100]
                batch = batch[100:]

    if batch:
        yield batch



def extract_chunks_from_text_content(user_id, source_id, source_title, text_content):

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=768,       
        chunk_overlap=150,    
        separators=[
            "\n\n",   
            "\n",
            ". ",
            " ",
            ""
        ]
    )
    chunks = splitter.create_documents(
        [text_content],
        metadatas=[{
            "user_id": user_id,
            "source_id": source_id,
            "source_name": source_title,
            "source_type": "text"
        }]
    )
    return chunks

def extract_chunks_from_url_content(user_id, source_id, url, text_content):
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=768,
        chunk_overlap=150,
        separators=[
            "\n\n",
            "\n",
            ". ",
            " ",
            ""
        ]
    )
    all_chunks = []
    for c in text_content[:1000]: 
        chunks = splitter.create_documents(
            [c.get("content")],
            metadatas=[{
                "user_id": user_id,
                "source_id": source_id,
                "source_name": url,
                "source_type": "url",
                "url": c.get("url"),
                "section": c.get("title")
            }]
        )
        all_chunks.extend(chunks)
    return all_chunks