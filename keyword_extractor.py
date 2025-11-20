import io
import re
import flet as ft
import pdfplumber
import requests
from bs4 import BeautifulSoup
from docx import Document

# ----------------------------
# Pomocnicze funkcje
# ----------------------------

def extract_text_from_url(url: str) -> list:
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
    except Exception as e:
        raise RuntimeError(f"Błąd przy pobieraniu strony: {e}")
    soup = BeautifulSoup(r.text, "html.parser")
    paragraphs = [p.get_text(separator=" ").strip() for p in soup.find_all("p") if p.get_text(strip=True)]
    if not paragraphs:
        text = soup.get_text("\n")
        paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    return paragraphs

def extract_text_from_pdf_bytes(pdf_bytes: bytes) -> list:
    paragraphs = []
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                text = page.extract_text() or ""
                text = re.sub(r"-\n", "", text)
                text = re.sub(r"\n+", " ", text)
                text = re.sub(r"\s{2,}", " ", text)
                page_pars = [p.strip() for p in re.split(r"(?<=[.!?])\s+", text) if p.strip()]
                paragraphs.extend(page_pars)
    except Exception as e:
        raise RuntimeError(f"Błąd przy odczycie PDF: {e}")
    return paragraphs

def paragraph_matches(paragraph: str, keywords: list) -> bool:
    for kw in keywords:
        if not kw:
            continue
        pattern = r"\b" + re.escape(kw) + r"\b"
        if re.search(pattern, paragraph, flags=re.IGNORECASE):
            return True
    return False

def bold_keywords(paragraph: str, keywords: list) -> str:
    def replacer(match):
        return f"*{match.group(0)}*"
    for kw in keywords:
        if not kw:
            continue
        pattern = re.compile(rf"\b{re.escape(kw)}\b", flags=re.IGNORECASE)
        paragraph = pattern.sub(replacer, paragraph)
    return paragraph

def build_result_text_with_sources(matching_paragraphs: list, keywords: list) -> str:
    lines = []
    for source, paragraph in matching_paragraphs:
        paragraph_bolded = bold_keywords(paragraph, keywords)
        lines.append(f"**Źródło: {source}**\n\n{paragraph_bolded}\n")
    return "\n---\n".join(lines)

def save_as_docx(text: str, path: str):
    clean_text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    doc = Document()
    for paragraph in clean_text.split("\n\n"):
        if paragraph.strip():
            doc.add_paragraph(paragraph.strip())
    doc.save(path)

def shorten_text(text, max_len=40):
    if len(text) <= max_len:
        return text
    else:
        return text[:max_len-3] + "..."

# ----------------------------
# Główna aplikacja Flet
# ----------------------------

def main(page: ft.Page):

    page.title = "Extractor: akapity ze słowami kluczowymi"
    page.padding = 20
    page.scroll = "auto"
    page.vertical_alignment = ft.MainAxisAlignment.START

    url_field = ft.TextField(label="Wklej URL (opcjonalnie)", width=700)
    keywords_field = ft.TextField(label="Słowa kluczowe (oddziel przecinkiem lub spacją)", width=700)

    file_picker = ft.FilePicker()
    page.overlay.append(file_picker)

    picked_files_display = ft.Text("Brak wybranych plików")

    source_paragraphs = {}
    keywords = []

    source_checkboxes = {}
    filter_column = ft.Column()

    def pick_files_result(e: ft.FilePickerResultEvent):
        if e.files:
            names = ", ".join([f.name for f in e.files])
            picked_files_display.value = names
        else:
            picked_files_display.value = "Brak wybranych plików"
        page.update()

    file_picker.on_result = pick_files_result

    output_area = ft.Markdown(value="", selectable=True, expand=True)

    progress_bar = ft.ProgressBar(width=700, value=0, visible=False)
    progress_text = ft.Text("", visible=False)

    def update_output(e=None):
        selected_sources = [src for src, cb in source_checkboxes.items() if cb.value]
        matching_paragraphs = []
        seen = set()
        for source in selected_sources:
            paragraphs = source_paragraphs.get(source, [])
            for p in paragraphs:
                if paragraph_matches(p, keywords):
                    key = p[:200]
                    if key not in seen:
                        matching_paragraphs.append((source, p))
                        seen.add(key)
        result_text = build_result_text_with_sources(matching_paragraphs, keywords)
        output_area.value = result_text
        page.update()

    def process_click(e):
        nonlocal source_paragraphs, keywords

        url = url_field.value.strip()
        keywords_raw = keywords_field.value.strip()

        if not url and not file_picker.result:
            page.snack_bar = ft.SnackBar(ft.Text("Podaj URL lub wybierz plik(i) PDF"), open=True)
            page.update()
            return
        if not keywords_raw:
            page.snack_bar = ft.SnackBar(ft.Text("Podaj przynajmniej jedno słowo kluczowe"), open=True)
            page.update()
            return

        keywords = [k.strip() for k in re.split(r"[\s,]+", keywords_raw) if k.strip()]
        source_paragraphs = {}

        filter_column.controls.clear()
        source_checkboxes.clear()

        progress_bar.visible = True
        progress_text.visible = True
        page.update()

        if url:
            try:
                url_pars = extract_text_from_url(url)
                source_paragraphs[f"URL: {url}"] = url_pars
            except Exception as ex:
                page.snack_bar = ft.SnackBar(ft.Text(str(ex)), open=True)
                progress_bar.visible = False
                progress_text.visible = False
                page.update()
                return

        if file_picker.result and file_picker.result.files:
            total_files = len(file_picker.result.files)
            for i, f in enumerate(file_picker.result.files):
                try:
                    with open(f.path, "rb") as fh:
                        pdf_bytes = fh.read()
                    pdf_pars = extract_text_from_pdf_bytes(pdf_bytes)
                    source_paragraphs[f"Plik PDF: {f.name}"] = pdf_pars
                except Exception as ex:
                    page.snack_bar = ft.SnackBar(ft.Text(str(ex)), open=True)
                    progress_bar.visible = False
                    progress_text.visible = False
                    page.update()
                    return
                progress_bar.value = (i + 1) / total_files
                progress_text.value = f"Przetwarzanie plików: {i+1}/{total_files}"
                page.update()

        progress_bar.visible = False
        progress_text.visible = False

        # Dodaj checkboxy filtrów z ograniczoną długością nazwy i tooltipem
        for source in source_paragraphs.keys():
            label = shorten_text(source, max_len=40)
            cb = ft.Checkbox(label=label, value=True, on_change=update_output, width=280)
            container = ft.Container(content=cb, width=280, tooltip=source)
            source_checkboxes[source] = cb
            filter_column.controls.append(container)
        page.update()

        update_output()

    result_container = ft.Container(
        content=ft.ListView(
            controls=[output_area],
            expand=True,
            spacing=10,
            padding=10,
            auto_scroll=True,
        ),
        width=700,
        height=400,
        border=ft.border.all(1),
        border_radius=10,
        padding=10,
    )

    save_picker = ft.FilePicker()
    page.overlay.append(save_picker)

    def on_save_result(ev: ft.FilePickerResultEvent):
        if not ev.path:
            return
        path = ev.path
        if not path.lower().endswith(".docx"):
            path = path.rstrip(".") + ".docx"
        try:
            save_as_docx(output_area.value, path)
            page.snack_bar = ft.SnackBar(ft.Text(f"Zapisano: {path}"), open=True)
        except Exception as err:
            page.snack_bar = ft.SnackBar(ft.Text(f"Błąd zapisu: {err}"), open=True)
        page.update()

    save_picker.on_result = on_save_result

    def save_to_disk(_e=None):
        save_picker.save_file(allowed_extensions=["docx"])

    save_button = ft.ElevatedButton("💾 Zapisz wynik", on_click=save_to_disk)
    process_btn = ft.ElevatedButton("Przetwórz", on_click=process_click)

    filter_box = ft.Container(
        content=ft.Column([
            ft.Text("Filtruj po źródle:", weight=600),
            filter_column,
        ], scroll="auto", height=400),
        width=300,
        border=ft.border.all(1),
        padding=10,
        margin=10,
    )

    page.add(
        ft.Column([
            ft.Text("Extractor - znajdź akapity ze słowami kluczowymi", style="headlineMedium"),
            url_field,
            ft.Row([
                ft.ElevatedButton(
                    "Wybierz PDF(y)",
                    on_click=lambda e: file_picker.pick_files(allow_multiple=True, allowed_extensions=["pdf"]),
                ),
                picked_files_display,
            ]),
            keywords_field,
            process_btn,
            progress_bar,
            progress_text,
            ft.Divider(),
            ft.Row([
                filter_box,
                result_container,
            ], spacing=10),
            ft.Container(  # poprawione dodanie paddingu do przycisku zapisu
                content=ft.Row([save_button], alignment=ft.MainAxisAlignment.START),
                padding=10,
                width=700,
            ),
        ], scroll="auto", expand=True, spacing=10)
    )

# ----------------------------
# Uruchomienie (desktop)
# ----------------------------
# Change the last part of your code to:
if __name__ == "__main__":
    try:
        ft.app(target=main, view=ft.WEB_BROWSER)
    except Exception as e:
        print(f"Błąd podczas uruchamiania aplikacji: {e}")

        input("Naciśnij Enter, aby zakończyć...")
