"""
Административная панель — управление учениками в PostgreSQL.
Запуск: python admin.py
"""

import pygame
import sys
import os
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()
DB_URL = os.getenv("DATABASE_URL")

pygame.init()

# ── Цвета ─────────────────────────────────────────────────────────
BG          = (245, 245, 248)
PANEL_BG    = (255, 255, 255)
ACCENT      = (70,  120, 220)
ACCENT_DARK = (50,   90, 180)
RED         = (210,  60,  60)
RED_DARK    = (170,  30,  30)
GREEN_C     = (60,  170,  80)
YELLOW_C    = (200, 140,   0)
TEXT        = (30,   30,  40)
TEXT_MUTED  = (130, 130, 150)
SELECTED_BG = (220, 232, 255)
DIVIDER     = (220, 220, 228)
WHITE       = (255, 255, 255)

# ── Шрифты ────────────────────────────────────────────────────────
F_TITLE  = pygame.font.SysFont("arial", 28, bold=True)
F_BODY   = pygame.font.SysFont("arial", 20)
F_SMALL  = pygame.font.SysFont("arial", 16)
F_BUTTON = pygame.font.SysFont("arial", 18, bold=True)

W, H = 920, 640
screen = pygame.display.set_mode((W, H), pygame.RESIZABLE)
pygame.display.set_caption("Панель администратора — Брайль")
clock = pygame.time.Clock()


# ══════════════════════════════════════════════════════════════════
#  БАЗА ДАННЫХ
# ══════════════════════════════════════════════════════════════════
def db_connect():
    return psycopg2.connect(DB_URL, connect_timeout=10)


def db_get_students() -> list:
    with db_connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("""
                SELECT
                    s.student_id,
                    COUNT(r.id)                AS total_dictations,
                    COALESCE(SUM(r.errors), 0) AS total_errors,
                    ROUND(AVG(r.grade), 1)     AS avg_grade,
                    MAX(r.date)                AS last_date
                FROM students s
                LEFT JOIN dictation_results r ON r.student_id = s.student_id
                GROUP BY s.student_id
                ORDER BY
                    CAST(
                        REGEXP_REPLACE(s.student_id, '[^0-9]', '', 'g')
                        AS INTEGER
                    ) NULLS LAST
            """)
            return [dict(r) for r in cur.fetchall()]


def db_delete_student(student_id: str):
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM students WHERE student_id = %s",
                (student_id,)
            )


# ══════════════════════════════════════════════════════════════════
#  РИСОВАНИЕ
# ══════════════════════════════════════════════════════════════════
def draw_rounded(surface, color, rect, r=10):
    pygame.draw.rect(surface, color, rect, border_radius=r)


def draw_button(surface, rect, text, color, hover, font=F_BUTTON) -> bool:
    hovered = rect.collidepoint(pygame.mouse.get_pos())
    draw_rounded(surface, hover if hovered else color, rect, r=8)
    s = font.render(text, True, WHITE)
    surface.blit(s, s.get_rect(center=rect.center))
    return hovered


def grade_color(avg):
    if avg is None:
        return TEXT_MUTED
    v = float(avg)
    return GREEN_C if v >= 9 else (YELLOW_C if v >= 7 else RED)


# ══════════════════════════════════════════════════════════════════
#  МОДАЛЬНЫЙ ДИАЛОГ
# ══════════════════════════════════════════════════════════════════
def modal_confirm(student_id: str) -> str | None:
    overlay = pygame.Surface((W, H), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, 160))
    screen.blit(overlay, (0, 0))

    mw, mh = 440, 210
    mx, my = (W - mw) // 2, (H - mh) // 2
    draw_rounded(screen, WHITE, pygame.Rect(mx, my, mw, mh), r=14)
    pygame.draw.rect(screen, DIVIDER,
                     pygame.Rect(mx, my, mw, mh), width=1, border_radius=14)

    s = F_BODY.render("Удалить ученика?", True, TEXT)
    screen.blit(s, s.get_rect(centerx=mx + mw // 2, y=my + 28))

    sid_s = F_TITLE.render(student_id, True, RED)
    screen.blit(sid_s, sid_s.get_rect(centerx=mx + mw // 2, y=my + 62))

    warn = F_SMALL.render(
        "Все результаты диктантов будут удалены безвозвратно.", True, TEXT_MUTED
    )
    screen.blit(warn, warn.get_rect(centerx=mx + mw // 2, y=my + 112))

    btn_cancel  = pygame.Rect(mx + 30,       my + 152, 170, 40)
    btn_confirm = pygame.Rect(mx + mw - 200, my + 152, 170, 40)
    draw_button(screen, btn_cancel,  "Отмена",  ACCENT, ACCENT_DARK)
    draw_button(screen, btn_confirm, "Удалить", RED,    RED_DARK)

    for ev in pygame.event.get():
        if ev.type == pygame.QUIT:
            pygame.quit(); sys.exit()
        if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
            return "cancel"
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            if btn_cancel.collidepoint(ev.pos):
                return "cancel"
            if btn_confirm.collidepoint(ev.pos):
                return "confirm"
    return None


# ══════════════════════════════════════════════════════════════════
#  ПАНЕЛЬ
# ══════════════════════════════════════════════════════════════════
class AdminPanel:
    ROW_H    = 52
    HDR_H    = 48
    LIST_TOP = 158
    PAD      = 24

    def __init__(self):
        self.students:       list       = []
        self.selected:       str | None = None
        self.confirm_target: str | None = None
        self.scroll   = 0
        self.status   = ""
        self.status_ok = True
        self.db_error  = ""
        self._load()

    # ── Данные ────────────────────────────────────────────────────
    def _load(self):
        try:
            self.students = db_get_students()
            self.db_error = ""
        except Exception as e:
            self.db_error = f"Ошибка БД: {e}"
            self.students = []

    def _delete(self, sid: str):
        try:
            db_delete_student(sid)
            self.status    = f"✓ {sid} удалён"
            self.status_ok = True
            if self.selected == sid:
                self.selected = None
            self._load()
        except Exception as e:
            self.status    = f"Ошибка: {e}"
            self.status_ok = False

    # ── Прокрутка ─────────────────────────────────────────────────
    def _max_scroll(self):
        return max(0, len(self.students) * self.ROW_H - (H - self.LIST_TOP - 10))

    def _clamp_scroll(self):
        self.scroll = max(0, min(self.scroll, self._max_scroll()))

    # ── Колонки ───────────────────────────────────────────────────
    def _cols(self):
        x = self.PAD + 8
        return {
            "id":    x,
            "dict":  x + 150,
            "err":   x + 290,
            "grade": x + 430,
            "date":  x + 550,
            "btn":   W - 130,
        }

    # ── Отрисовка ─────────────────────────────────────────────────
    def draw(self):
        screen.fill(BG)

        # Шапка
        draw_rounded(screen, PANEL_BG,
                     pygame.Rect(0, 0, W, 130), r=0)
        pygame.draw.line(screen, DIVIDER, (0, 130), (W, 130))

        screen.blit(F_TITLE.render("Панель администратора", True, TEXT),
                    (self.PAD, 18))
        screen.blit(F_SMALL.render(
            f"Учеников в базе: {len(self.students)}  |  "
            "↑↓ — выбор   Delete — удалить   F5 — обновить",
            True, TEXT_MUTED), (self.PAD, 54))

        # Кнопка обновить
        btn_ref = pygame.Rect(W - 164, 20, 140, 38)
        draw_button(screen, btn_ref, "↻  Обновить", ACCENT, ACCENT_DARK)

        # Статус
        if self.db_error:
            screen.blit(F_SMALL.render(self.db_error, True, RED),
                        (self.PAD, 84))
        elif self.status:
            col = GREEN_C if self.status_ok else RED
            screen.blit(F_SMALL.render(self.status, True, col),
                        (self.PAD, 84))

        # Заголовок таблицы
        cols = self._cols()
        hdr_rect = pygame.Rect(self.PAD,
                               self.LIST_TOP - self.HDR_H,
                               W - self.PAD * 2,
                               self.HDR_H - 4)
        draw_rounded(screen, ACCENT, hdr_rect, r=10)
        labels = [
            ("Ученик",  cols["id"],    90),
            ("Диктантов", cols["dict"], 30),
            ("Ошибок", cols["err"],   30),
            ("Ср. оценка", cols["grade"], 50),
            ("Последний сеанс", cols["date"], 150),
        ]
        for lbl, cx, w in labels:
            s = F_BUTTON.render(lbl, True, WHITE)
            text_rect = s.get_rect(center=(
                cx + w // 2,
                hdr_rect.y + (self.HDR_H - 4) // 2
            ))
            screen.blit(s, text_rect)

        # Строки
        clip = pygame.Rect(0, self.LIST_TOP, W, H - self.LIST_TOP - 10)
        screen.set_clip(clip)

        for i, st in enumerate(self.students):
            ry = self.LIST_TOP + i * self.ROW_H - self.scroll
            if ry + self.ROW_H < self.LIST_TOP or ry > H:
                continue

            rr = pygame.Rect(self.PAD, ry, W - self.PAD * 2, self.ROW_H - 4)
            is_sel = st["student_id"] == self.selected
            bg = SELECTED_BG if is_sel else (
                PANEL_BG if i % 2 == 0 else (250, 250, 253)
            )
            draw_rounded(screen, bg, rr, r=8)
            if is_sel:
                pygame.draw.rect(screen, ACCENT, rr, width=2, border_radius=8)

            cy = ry + (self.ROW_H - 4 - F_BODY.get_height()) // 2

            def txt(text, col, cx, font=F_BODY):
                screen.blit(font.render(str(text), True, col), (cx, cy))

            txt(st["student_id"],           TEXT,       cols["id"])
            txt(st["total_dictations"] or 0, TEXT_MUTED, cols["dict"])
            txt(st["total_errors"] or 0,
                RED if (st["total_errors"] or 0) > 0 else TEXT_MUTED,
                cols["err"])
            grade_str = (f"{float(st['avg_grade']):.1f}"
                         if st["avg_grade"] else "—")
            txt(grade_str, grade_color(st["avg_grade"]), cols["grade"])
            txt(st["last_date"] or "—", TEXT_MUTED, cols["date"])

            # Кнопка удалить
            btn_del = pygame.Rect(cols["btn"], ry + 10,
                                  W - self.PAD - cols["btn"] - 8,
                                  self.ROW_H - 22)
            draw_button(screen, btn_del, "Удалить", RED, RED_DARK, font=F_SMALL)

        screen.set_clip(None)
        self._draw_scrollbar()

    def _draw_scrollbar(self):
        ms = self._max_scroll()
        if ms <= 0:
            return
        th = H - self.LIST_TOP - 10
        sh = max(30, th * th // (th + ms))
        sy = self.LIST_TOP + (th - sh) * self.scroll // ms
        pygame.draw.rect(screen, DIVIDER,
                         pygame.Rect(W - 10, self.LIST_TOP, 6, th), border_radius=3)
        pygame.draw.rect(screen, ACCENT,
                         pygame.Rect(W - 10, sy, 6, sh), border_radius=3)

    # ── События ───────────────────────────────────────────────────
    def handle(self, ev):
        global W, H

        if ev.type == pygame.VIDEORESIZE:
            W, H = ev.w, ev.h
            pygame.display.set_mode((W, H), pygame.RESIZABLE)

        elif ev.type == pygame.MOUSEWHEEL:
            self.scroll -= ev.y * self.ROW_H
            self._clamp_scroll()

        elif ev.type == pygame.KEYDOWN:
            if ev.key == pygame.K_UP:
                self._move(-1)
            elif ev.key == pygame.K_DOWN:
                self._move(1)
            elif ev.key == pygame.K_DELETE and self.selected:
                self.confirm_target = self.selected
            elif ev.key == pygame.K_F5:
                self._load()
                self.status    = "Данные обновлены"
                self.status_ok = True

        elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            mx, my = ev.pos

            # Кнопка обновить
            if pygame.Rect(W - 164, 20, 140, 38).collidepoint(mx, my):
                self._load()
                self.status    = "Данные обновлены"
                self.status_ok = True
                return

            if my < self.LIST_TOP:
                return

            idx = (my - self.LIST_TOP + self.scroll) // self.ROW_H
            if not (0 <= idx < len(self.students)):
                return

            st  = self.students[idx]
            sid = st["student_id"]
            cols = self._cols()

            ry_btn = self.LIST_TOP + idx * self.ROW_H - self.scroll
            btn_del = pygame.Rect(cols["btn"], ry_btn + 10,
                                  W - self.PAD - cols["btn"] - 8,
                                  self.ROW_H - 22)
            if btn_del.collidepoint(mx, my):
                self.confirm_target = sid
            else:
                self.selected = sid

    def _move(self, d: int):
        if not self.students:
            return
        ids = [s["student_id"] for s in self.students]
        idx = ids.index(self.selected) if self.selected in ids else -1
        idx = max(0, min(len(ids) - 1, idx + d))
        self.selected = ids[idx]
        # Автопрокрутка
        ry = idx * self.ROW_H
        vis = H - self.LIST_TOP
        if ry < self.scroll:
            self.scroll = ry
        elif ry + self.ROW_H > self.scroll + vis:
            self.scroll = ry + self.ROW_H - vis
        self._clamp_scroll()

    # ── Главный цикл ──────────────────────────────────────────────
    def run(self):
        while True:
            if self.confirm_target:
                self.draw()
                result = modal_confirm(self.confirm_target)
                if result == "confirm":
                    self._delete(self.confirm_target)
                    self.confirm_target = None
                elif result == "cancel":
                    self.confirm_target = None
            else:
                for ev in pygame.event.get():
                    if ev.type == pygame.QUIT:
                        pygame.quit(); sys.exit()
                    self.handle(ev)
                self.draw()

            pygame.display.flip()
            clock.tick(60)


if __name__ == "__main__":
    AdminPanel().run()