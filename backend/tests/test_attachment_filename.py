"""Файл с РУССКИМ именем отдаётся, а не роняет ответ (20.09.2026).

Приложенные к инструкциям руководства называются по-русски. Заголовок
`Content-Disposition` собирался как `filename*=UTF-8''<имя>` БЕЗ процентного
кодирования, которого требует RFC 5987; HTTP-заголовки кодируются latin-1,
поэтому отдача падала с UnicodeEncodeError и 500. Значок «📎 файл» в разделе
был, материал открывался, а скачать его было нельзя.

Дефект не проявлялся ровно потому, что файлов в разделе не было ни одного, и
ни один тест его не видел: проверялась загрузка, а не скачивание.

Сборка заголовка теперь общая для всех мест, где отдаётся файл.
"""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

from app import db
from app.exports import attachment_header


def test_header_survives_latin1_encoding():
    """Главное: заголовок обязан кодироваться latin-1 — иначе ответ падает."""
    for name in ("Руководство_пользователя.docx", "Отчёт: итоги/2026.xlsx",
                 "Сводка «МФЦ».pdf", "plain.csv", ""):
        h = attachment_header(name, "file.bin")
        h.encode("latin-1")  # именно здесь падало
        assert "filename*=UTF-8''" in h


def test_header_keeps_the_real_name_and_a_usable_fallback():
    h = attachment_header("Руководство_пользователя.docx", "instruction.docx")
    # Настоящее имя — в filename*, процентным кодированием.
    assert "%D0%A0" in h, "русское имя потерялось"
    # ASCII-запасной не должен вырождаться в «_.docx» — почти безымянный файл.
    assert 'filename="instruction.docx"' in h
    # Латиница остаётся как есть.
    assert 'filename="report.csv"' in attachment_header("report.csv", "file")
    # Разделители путей и кавычки в имя файла попасть не должны.
    assert "/" not in attachment_header("итоги/2026.xlsx", "file").split("filename*")[0]


async def test_instruction_file_downloads(client, admin_headers, viewer):
    """Сквозной путь: приложили файл с русским именем — он скачивается."""
    created = await client.post("/instructions", headers=admin_headers, json={
        "title": "ztest материал с файлом", "section": "ztest", "is_published": True})
    iid = created.json()["id"]
    try:
        name = "Руководство_пользователя.docx"
        ctype = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        up = await client.post(f"/instructions/{iid}/file", headers=admin_headers,
                               files={"file": (name, b"PK\x03\x04ztest", ctype)})
        assert up.status_code == 200, up.text

        r = await client.get(f"/instructions/{iid}/file", headers=viewer["headers"])
        assert r.status_code == 200, f"скачивание упало: {r.status_code}"
        assert r.content == b"PK\x03\x04ztest", "содержимое файла испорчено"
        cd = r.headers["content-disposition"]
        cd.encode("latin-1")
        assert "%D0%A0%D1%83%D0%BA" in cd, "русское имя не доехало до заголовка"
    finally:
        async with db.acquire() as conn:
            await conn.execute("delete from instructions where id=$1::uuid", iid)


async def test_sections_are_ordered_by_position_not_alphabet(client, admin_headers):
    """Порядок разделов задаёт человек, а не алфавит.

    При сортировке по названию рядовой пользователь первым видел «Для
    администратора», а «Начало работы» оказывалось в середине списка."""
    made = []
    try:
        for section, title, pos in (("яРаздел последний", "ztest поздний", 90),
                                    ("аРаздел первый по алфавиту", "ztest ранний", 91)):
            r = await client.post("/instructions", headers=admin_headers, json={
                "title": title, "section": section, "position": pos, "is_published": True})
            made.append(r.json()["id"])

        items = (await client.get("/instructions?drafts=true", headers=admin_headers)).json()["items"]
        order = [i["section"] for i in items if i["section"] in
                 ("яРаздел последний", "аРаздел первый по алфавиту")]
        assert order[0] == "яРаздел последний", (
            "разделы снова идут по алфавиту, а не по позиции: " + str(order))
    finally:
        async with db.acquire() as conn:
            for iid in made:
                await conn.execute("delete from instructions where id=$1::uuid", iid)
