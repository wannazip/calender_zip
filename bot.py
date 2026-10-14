import os
import re
import calendar
import sqlite3
from datetime import datetime, date
from urllib.parse import quote

import discord
from discord.ext import commands
from discord import app_commands

# =========================
# 기본 설정
# =========================
TOKEN = os.getenv("DISCORD_BOT_TOKEN", "access_token")
DB_PATH = os.getenv("CALENDAR_DB_PATH", "calendar.db")
KST = datetime.now().astimezone().tzinfo

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

calendar.setfirstweekday(calendar.SUNDAY)

# 달력 숫자 표기: 기존 디자인에 가까운 원문자 숫자
CIRCLED = {
    1: "①", 2: "②", 3: "③", 4: "④", 5: "⑤",
    6: "⑥", 7: "⑦", 8: "⑧", 9: "⑨", 10: "⑩",
    11: "⑪", 12: "⑫", 13: "⑬", 14: "⑭", 15: "⑮",
    16: "⑯", 17: "⑰", 18: "⑱", 19: "⑲", 20: "⑳",
    21: "㉑", 22: "㉒", 23: "㉓", 24: "㉔", 25: "㉕",
    26: "㉖", 27: "㉗", 28: "㉘", 29: "㉙", 30: "㉚",
    31: "㉛",
}


def db_connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db_connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                event_date TEXT NOT NULL,
                event_time TEXT,
                title TEXT NOT NULL,
                details TEXT,
                created_by INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_by INTEGER,
                updated_at TEXT
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_events_guild_date
            ON events(guild_id, event_date)
        """)


def get_events_for_month(guild_id: int, year: int, month: int):
    prefix = f"{year:04d}-{month:02d}-"
    with db_connect() as conn:
        return conn.execute(
            """SELECT * FROM events
               WHERE guild_id = ? AND event_date LIKE ?
               ORDER BY event_date, COALESCE(event_time, '99:99'), id""",
            (guild_id, prefix + "%")
        ).fetchall()


def get_events_for_date(guild_id: int, date_text: str):
    with db_connect() as conn:
        return conn.execute(
            """SELECT * FROM events
               WHERE guild_id = ? AND event_date = ?
               ORDER BY COALESCE(event_time, '99:99'), id""",
            (guild_id, date_text)
        ).fetchall()


def add_event(guild_id, event_date, event_time, title, details, user_id):
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    with db_connect() as conn:
        cur = conn.execute(
            """INSERT INTO events
               (guild_id, event_date, event_time, title, details, created_by, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (guild_id, event_date, event_time or None, title, details or None, user_id, now)
        )
        return cur.lastrowid


def update_event(event_id, guild_id, event_date, event_time, title, details, user_id):
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    with db_connect() as conn:
        cur = conn.execute(
            """UPDATE events
               SET event_date = ?, event_time = ?, title = ?, details = ?,
                   updated_by = ?, updated_at = ?
               WHERE id = ? AND guild_id = ?""",
            (event_date, event_time or None, title, details or None,
             user_id, now, event_id, guild_id)
        )
        return cur.rowcount > 0


def delete_event(event_id, guild_id):
    with db_connect() as conn:
        cur = conn.execute(
            "DELETE FROM events WHERE id = ? AND guild_id = ?",
            (event_id, guild_id)
        )
        return cur.rowcount > 0


def event_label(day: int, events):
    """달력 칸에 표시할 날짜 문자열과 선택적 링크를 만듭니다."""
    day_text = CIRCLED.get(day, str(day))

    if len(events) == 1:
        details = (events[0]["details"] or "").strip()

        if not details:
            return day_text

        # 디스코드 채널 링크는 입력된 URL을 그대로 사용합니다.
        if details.startswith((
            "https://discordapp.com/",
            "https://discord.com/"
        )):
            return f"[{day_text}]({details})"

        # 링크가 아닌 텍스트는 숨김 링크 형식으로 감쌉니다.
        return f"[{day_text}](https://./{details})"

    if len(events) > 1:
        # 여러 일정이 있는 날짜는 개수를 표시합니다.
        # 전체 일정은 '일정 전체 보기' 버튼에서 확인할 수 있습니다.
        return f"{day_text} ({len(events)})"

    return day_text


def render_calendar(guild_id: int, year: int, month: int) -> str:
    events = get_events_for_month(guild_id, year, month)
    by_day = {}
    for event in events:
        day = int(event["event_date"][-2:])
        by_day.setdefault(day, []).append(event)

    rows = calendar.monthcalendar(year, month)
    lines = [
        f"# {year}년 {month}월",
        "> # Su  Mo  Tu  We  Th  Fr  Sa",
    ]
    for week in rows:
        cells = []
        for day in week:
            if day == 0:
                cells.append("　 ")
            else:
                cells.append(event_label(day, by_day.get(day, [])))
        # 링크 길이와 Discord 마크다운 렌더링에 따라 완벽한 고정폭은 보장되지 않지만,
        # 기본 디자인은 사용자가 정한 인용문 + 제목 형식을 유지합니다.
        lines.append("> # " + "   ".join(cells))
    lines.append("")
    lines.append("_여러 일정이 있는 날짜는 날짜 옆에 일정 개수가 표시됩니다._")
    return "\n".join(lines)


def format_event(event):
    day = event["event_date"]
    time_text = f" · {event['event_time']}" if event["event_time"] else ""
    details = f"\n상세 설명: {event['details']}" if event["details"] else ""
    return f"**{day}{time_text} — {event['title']}**{details}\nID: `{event['id']}`"


def month_shift(year, month, offset):
    total = year * 12 + (month - 1) + offset
    return total // 12, total % 12 + 1


class EventModal(discord.ui.Modal):
    def __init__(self, year: int, month: int, event=None):
        self.year = year
        self.month = month
        self.event_id = event["id"] if event else None
        title = "일정 수정" if event else "일정 추가"
        super().__init__(title=title, timeout=300)

        self.date_input = discord.ui.TextInput(
            label="날짜 (YYYY-MM-DD)",
            placeholder=f"{year:04d}-{month:02d}-15",
            default=event["event_date"] if event else f"{year:04d}-{month:02d}-",
            max_length=10,
        )
        self.time_input = discord.ui.TextInput(
            label="시간 (선택, 예: 19:30)",
            required=False,
            default=(event["event_time"] or "") if event else "",
            max_length=5,
        )
        self.title_input = discord.ui.TextInput(
            label="일정 제목",
            placeholder="예: 9시에 마피아",
            default=event["title"] if event else "",
            max_length=100,
        )
        self.details_input = discord.ui.TextInput(
            label="상세 설명 또는 링크 (선택)",
            placeholder="링크 또는 원하는 텍스트를 입력하세요",
            default=(event["details"] or "") if event else "",
            required=False,
            style=discord.TextStyle.paragraph,
            max_length=1000,
        )
        for item in (self.date_input, self.time_input, self.title_input, self.details_input):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.guild_id is None:
            await interaction.response.send_message("서버 안에서만 사용할 수 있습니다.", ephemeral=True)
            return
        try:
            parsed = date.fromisoformat(self.date_input.value.strip())
        except ValueError:
            await interaction.response.send_message(
                "날짜 형식이 올바르지 않습니다. `YYYY-MM-DD` 형식으로 입력해 주세요.",
                ephemeral=True
            )
            return

        time_value = self.time_input.value.strip()
        if time_value and not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", time_value):
            await interaction.response.send_message(
                "시간은 `HH:MM` 형식으로 입력해 주세요. 예: `19:30`",
                ephemeral=True
            )
            return

        title_value = self.title_input.value.strip()
        if not title_value:
            await interaction.response.send_message("일정 제목은 필수입니다.", ephemeral=True)
            return

        details_value = self.details_input.value.strip()
        if self.event_id:
            update_event(
                self.event_id, interaction.guild_id, parsed.isoformat(),
                time_value, title_value, details_value, interaction.user.id
            )
            message = "일정을 수정했습니다."
        else:
            add_event(
                interaction.guild_id, parsed.isoformat(), time_value,
                title_value, details_value, interaction.user.id
            )
            message = "일정을 추가했습니다."

        view = CalendarView(parsed.year, parsed.month)
        await interaction.response.send_message(
            message + "\n\n" + render_calendar(interaction.guild_id, parsed.year, parsed.month),
            view=view,
            allowed_mentions=discord.AllowedMentions.none()
        )


class MonthJumpModal(discord.ui.Modal, title="원하는 연도와 월 조회"):
    year_input = discord.ui.TextInput(label="연도", placeholder="2026", max_length=4)
    month_input = discord.ui.TextInput(label="월 (1~12)", placeholder="10", max_length=2)

    def __init__(self):
        super().__init__(timeout=300)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            year = int(self.year_input.value.strip())
            month = int(self.month_input.value.strip())
            if not (1 <= year <= 9999 and 1 <= month <= 12):
                raise ValueError
        except ValueError:
            await interaction.response.send_message(
                "연도와 월을 올바르게 입력해 주세요. 월은 1~12입니다.",
                ephemeral=True
            )
            return
        if interaction.guild_id is None:
            await interaction.response.send_message("서버 안에서만 사용할 수 있습니다.", ephemeral=True)
            return
        await interaction.response.send_message(
            render_calendar(interaction.guild_id, year, month),
            view=CalendarView(year, month),
            allowed_mentions=discord.AllowedMentions.none()
        )


class EventSelect(discord.ui.Select):
    def __init__(self, events, mode):
        self.mode = mode
        options = []
        for event in events[:25]:
            time_text = f" {event['event_time']}" if event["event_time"] else ""
            label = f"{event['event_date']}{time_text} · {event['title']}"[:100]
            options.append(discord.SelectOption(label=label, value=str(event["id"])))
        super().__init__(
            placeholder="수정하거나 삭제할 일정을 선택하세요",
            min_values=1, max_values=1, options=options
        )

    async def callback(self, interaction: discord.Interaction):
        event_id = int(self.values[0])
        with db_connect() as conn:
            event = conn.execute(
                "SELECT * FROM events WHERE id = ? AND guild_id = ?",
                (event_id, interaction.guild_id)
            ).fetchone()
        if not event:
            await interaction.response.send_message("일정을 찾을 수 없습니다.", ephemeral=True)
            return
        if self.mode == "edit":
            await interaction.response.send_modal(EventModal(
                int(event["event_date"][:4]), int(event["event_date"][5:7]), event
            ))
        else:
            view = DeleteConfirmView(event_id, interaction.guild_id, event["title"])
            await interaction.response.send_message(
                f"다음 일정을 삭제하시겠습니까?\n{format_event(event)}",
                view=view,
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none()
            )


class EventManageView(discord.ui.View):
    def __init__(self, guild_id, year, month, mode):
        super().__init__(timeout=300)
        events = get_events_for_month(guild_id, year, month)
        if events:
            self.add_item(EventSelect(events, mode))


class DeleteConfirmView(discord.ui.View):
    def __init__(self, event_id, guild_id, title):
        super().__init__(timeout=60)
        self.event_id = event_id
        self.guild_id = guild_id
        self.event_title = title

    @discord.ui.button(label="삭제 확인", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        deleted = delete_event(self.event_id, self.guild_id)
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(
            content="일정을 삭제했습니다." if deleted else "이미 삭제되었거나 찾을 수 없는 일정입니다.",
            view=self
        )

    @discord.ui.button(label="취소", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(content="삭제를 취소했습니다.", view=self)


class CalendarView(discord.ui.View):
    def __init__(self, year=None, month=None, calendar_only=False):
        super().__init__(timeout=None)
        now = datetime.now().astimezone()
        self.year = year or now.year
        self.month = month or now.month
        self.calendar_only = calendar_only

        prev_year, prev_month = month_shift(self.year, self.month, -1)
        next_year, next_month = month_shift(self.year, self.month, 1)

        prev_button = discord.ui.Button(label="◀ 이전 달", style=discord.ButtonStyle.secondary, row=0)
        prev_button.callback = self.make_month_callback(prev_year, prev_month)
        self.add_item(prev_button)

        jump_button = discord.ui.Button(label="연도·월 조회", style=discord.ButtonStyle.primary, row=0)
        jump_button.callback = self.jump_month
        self.add_item(jump_button)

        next_button = discord.ui.Button(label="다음 달 ▶", style=discord.ButtonStyle.secondary, row=0)
        next_button.callback = self.make_month_callback(next_year, next_month)
        self.add_item(next_button)

        add_button = discord.ui.Button(label="일정 추가", style=discord.ButtonStyle.success, row=1)
        add_button.callback = self.add_event
        self.add_item(add_button)

        all_button = discord.ui.Button(label="일정 전체 보기", style=discord.ButtonStyle.primary, row=1)
        all_button.callback = self.show_all_events
        self.add_item(all_button)

        if not calendar_only:
            edit_button = discord.ui.Button(label="일정 수정", style=discord.ButtonStyle.secondary, row=2)
            edit_button.callback = self.edit_event
            self.add_item(edit_button)

            delete_button = discord.ui.Button(label="일정 삭제", style=discord.ButtonStyle.danger, row=2)
            delete_button.callback = self.delete_event
            self.add_item(delete_button)

            only_button = discord.ui.Button(label="달력만 보기", style=discord.ButtonStyle.secondary, row=2)
            only_button.callback = self.show_calendar_only
            self.add_item(only_button)
        else:
            full_button = discord.ui.Button(label="관리 메뉴 보기", style=discord.ButtonStyle.secondary, row=2)
            full_button.callback = self.show_full_menu
            self.add_item(full_button)

    def make_month_callback(self, year, month):
        async def callback(interaction: discord.Interaction):
            if interaction.guild_id is None:
                await interaction.response.send_message("서버 안에서만 사용할 수 있습니다.", ephemeral=True)
                return
            await interaction.response.edit_message(
                content=render_calendar(interaction.guild_id, year, month),
                view=CalendarView(year, month, self.calendar_only),
                allowed_mentions=discord.AllowedMentions.none()
            )
        return callback

    async def jump_month(self, interaction: discord.Interaction):
        await interaction.response.send_modal(MonthJumpModal())

    async def add_event(self, interaction: discord.Interaction):
        await interaction.response.send_modal(EventModal(self.year, self.month))

    async def show_all_events(self, interaction: discord.Interaction):
        if interaction.guild_id is None:
            await interaction.response.send_message("서버 안에서만 사용할 수 있습니다.", ephemeral=True)
            return
        events = get_events_for_month(interaction.guild_id, self.year, self.month)
        if not events:
            content = f"**{self.year}년 {self.month}월** 등록된 일정이 없습니다."
        else:
            header = f"**{self.year}년 {self.month}월 일정 전체 보기**\n"
            body = "\n\n".join(format_event(event) for event in events)
            content = header + body
            if len(content) > 1900:
                content = content[:1850] + "\n\n일정이 많아 일부 내용만 표시했습니다."
        await interaction.response.send_message(
            content,
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none()
        )

    async def edit_event(self, interaction: discord.Interaction):
        if interaction.guild_id is None:
            await interaction.response.send_message("서버 안에서만 사용할 수 있습니다.", ephemeral=True)
            return
        events = get_events_for_month(interaction.guild_id, self.year, self.month)
        if not events:
            await interaction.response.send_message("수정할 일정이 없습니다.", ephemeral=True)
            return
        if len(events) > 25:
            await interaction.response.send_message(
                "이 달에 일정이 25개를 초과합니다. 현재 버전에서는 선택 목록에 최대 25개까지만 표시됩니다.",
                ephemeral=True
            )
            return
        await interaction.response.send_message(
            "수정할 일정을 선택해 주세요.",
            view=EventManageView(interaction.guild_id, self.year, self.month, "edit"),
            ephemeral=True
        )

    async def delete_event(self, interaction: discord.Interaction):
        if interaction.guild_id is None:
            await interaction.response.send_message("서버 안에서만 사용할 수 있습니다.", ephemeral=True)
            return
        events = get_events_for_month(interaction.guild_id, self.year, self.month)
        if not events:
            await interaction.response.send_message("삭제할 일정이 없습니다.", ephemeral=True)
            return
        if len(events) > 25:
            await interaction.response.send_message(
                "이 달에 일정이 25개를 초과합니다. 현재 버전에서는 선택 목록에 최대 25개까지만 표시됩니다.",
                ephemeral=True
            )
            return
        await interaction.response.send_message(
            "삭제할 일정을 선택해 주세요.",
            view=EventManageView(interaction.guild_id, self.year, self.month, "delete"),
            ephemeral=True
        )

    async def show_calendar_only(self, interaction: discord.Interaction):
        await interaction.response.edit_message(
            content=render_calendar(interaction.guild_id, self.year, self.month),
            view=CalendarView(self.year, self.month, calendar_only=True),
            allowed_mentions=discord.AllowedMentions.none()
        )

    async def show_full_menu(self, interaction: discord.Interaction):
        await interaction.response.edit_message(
            content=render_calendar(interaction.guild_id, self.year, self.month),
            view=CalendarView(self.year, self.month, calendar_only=False),
            allowed_mentions=discord.AllowedMentions.none()
        )


@bot.event
async def on_ready():
    init_db()
    try:
        synced = await bot.tree.sync()
        print(f"슬래시 명령어 {len(synced)}개 동기화 완료")
    except Exception as exc:
        print(f"명령어 동기화 실패: {exc}")
    print(f"로그인 완료: {bot.user} (ID: {bot.user.id})")


@bot.tree.command(name="달력", description="이번 달 달력 또는 원하는 연도·월의 달력을 표시합니다.")
@app_commands.describe(year="조회할 연도 (생략하면 올해)", month="조회할 월 1~12 (생략하면 이번 달)")
async def calendar_command(
    interaction: discord.Interaction,
    year: app_commands.Range[int, 1, 9999] | None = None,
    month: app_commands.Range[int, 1, 12] | None = None
):
    if interaction.guild_id is None:
        await interaction.response.send_message("서버 안에서만 사용할 수 있습니다.", ephemeral=True)
        return
    now = datetime.now().astimezone()
    chosen_year = year if year is not None else now.year
    chosen_month = month if month is not None else (now.month if year is None or month is None else month)
    # 연도만 지정하면 현재 월, 월만 지정하면 현재 연도를 사용합니다.
    if year is not None and month is None:
        chosen_month = now.month
    if month is not None and year is None:
        chosen_year = now.year
    await interaction.response.send_message(
        render_calendar(interaction.guild_id, chosen_year, chosen_month),
        view=CalendarView(chosen_year, chosen_month),
        allowed_mentions=discord.AllowedMentions.none()
    )


if __name__ == "__main__":
    if TOKEN == "여기에_디스코드_봇_토큰을_넣으세요":
        raise SystemExit(
            "DISCORD_BOT_TOKEN 환경변수에 봇 토큰을 설정하거나 코드의 TOKEN 값을 입력해 주세요."
        )
    init_db()
    bot.run(TOKEN)
