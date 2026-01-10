import discord
from openai import AsyncOpenAI
from redbot.core import commands, Config, checks
from redbot.core.bot import Red
from typing import Optional


class OpenAIChat(commands.Cog):
    """Cog do komunikacji z API OpenAI w trybie konwersacji"""

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(
            self,
            identifier=1234567890,  # Unikalny identyfikator coga
            force_registration=True,
        )

        default_guild = {
            "api_key": None,
            "model": "gpt-4o-mini",
            "max_history": 10,
            "max_tokens": 100,
            "system_prompt": "Jesteś pomocnym asystentem AI.",
        }

        self.config.register_guild(**default_guild)

        # Historia konwersacji przechowywana w pamięci: {user_id: [messages]}
        self.conversation_history: dict[int, list[dict]] = {}

    def _get_client(self, api_key: str) -> AsyncOpenAI:
        """Tworzy klienta OpenAI z podanym kluczem API"""
        return AsyncOpenAI(api_key=api_key)

    def _get_user_history(self, user_id: int) -> list[dict]:
        """Pobiera historię konwersacji użytkownika"""
        if user_id not in self.conversation_history:
            self.conversation_history[user_id] = []
        return self.conversation_history[user_id]

    def _add_to_history(self, user_id: int, role: str, content: str, max_history: int):
        """Dodaje wiadomość do historii i ogranicza jej rozmiar"""
        history = self._get_user_history(user_id)
        history.append({"role": role, "content": content})

        # Ograniczenie historii do max_history wiadomości (pary user/assistant)
        max_messages = max_history * 2
        if len(history) > max_messages:
            self.conversation_history[user_id] = history[-max_messages:]

    async def _split_message(self, content: str) -> list[str]:
        """Dzieli długą wiadomość na części <= 2000 znaków"""
        if len(content) <= 2000:
            return [content]

        parts = []
        while content:
            if len(content) <= 2000:
                parts.append(content)
                break

            # Znajdź miejsce do podziału (koniec linii lub spacja)
            split_pos = content.rfind("\n", 0, 2000)
            if split_pos == -1:
                split_pos = content.rfind(" ", 0, 2000)
            if split_pos == -1:
                split_pos = 2000

            parts.append(content[:split_pos])
            content = content[split_pos:].lstrip()

        return parts

    @commands.command(name="ask")
    async def ask(self, ctx: commands.Context, *, prompt: str):
        """Wysyła prompt do OpenAI i zwraca odpowiedź

        Przykład: [p]ask Jak działa fotosynteza?
        """
        api_key = await self.config.guild(ctx.guild).api_key()

        if not api_key:
            await ctx.send(
                "Klucz API OpenAI nie jest ustawiony. "
                "Administrator musi użyć komendy `[p]aiset apikey` aby go ustawić."
            )
            return

        model = await self.config.guild(ctx.guild).model()
        max_history = await self.config.guild(ctx.guild).max_history()
        max_tokens = await self.config.guild(ctx.guild).max_tokens()
        system_prompt = await self.config.guild(ctx.guild).system_prompt()

        # Pobierz historię użytkownika
        user_history = self._get_user_history(ctx.author.id)

        # Przygotuj wiadomości dla API
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(user_history)
        messages.append({"role": "user", "content": prompt})

        # Pokaż, że bot "pisze"
        async with ctx.typing():
            try:
                client = self._get_client(api_key)
                response = await client.chat.completions.create(
                    model=model,
                    messages=messages,
                    max_tokens=max_tokens,
                )

                ai_response = response.choices[0].message.content

                # Dodaj do historii
                self._add_to_history(ctx.author.id, "user", prompt, max_history)
                self._add_to_history(ctx.author.id, "assistant", ai_response, max_history)

                # Wyślij odpowiedź (podziel jeśli za długa)
                header = f"**Prompt od {ctx.author.mention}:** {prompt}\n\n"
                full_response = header + (ai_response or "")
                parts = await self._split_message(full_response)
                for part in parts:
                    await ctx.send(part)

            except Exception as e:
                await ctx.send(f"Wystąpił błąd podczas komunikacji z OpenAI: {str(e)}")

    @commands.command(name="aiclear")
    async def aiclear(self, ctx: commands.Context):
        """Czyści historię konwersacji użytkownika"""
        user_id = ctx.author.id

        if user_id in self.conversation_history:
            self.conversation_history[user_id] = []
            await ctx.send("Twoja historia konwersacji została wyczyszczona.")
        else:
            await ctx.send("Nie masz żadnej historii konwersacji do wyczyszczenia.")

    @commands.group(name="aiset")
    @checks.admin_or_permissions(administrator=True)
    async def aiset(self, ctx: commands.Context):
        """Komendy konfiguracyjne dla OpenAI Chat"""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @aiset.command(name="apikey")
    async def aiset_apikey(self, ctx: commands.Context, api_key: str):
        """Ustawia klucz API OpenAI

        Zalecane jest użycie tej komendy w wiadomości prywatnej (DM) do bota.
        Komenda automatycznie usunie Twoją wiadomość z kluczem.
        """
        # Usuń wiadomość użytkownika z kluczem API (dla bezpieczeństwa)
        try:
            await ctx.message.delete()
        except (discord.Forbidden, discord.HTTPException):
            pass

        await self.config.guild(ctx.guild).api_key.set(api_key)
        await ctx.send(
            "Klucz API OpenAI został ustawiony. "
            "Twoja wiadomość z kluczem została usunięta dla bezpieczeństwa.",
            delete_after=10,
        )

    @aiset.command(name="model")
    async def aiset_model(self, ctx: commands.Context, model: str):
        """Ustawia model OpenAI do użycia

        Polecane dostępne modele: gpt-5-nano, gpt-5-mini, gpt-4o, gpt-4o-mini, gpt-4-turbo, gpt-3.5-turbo, itp.
        Domyślnie: gpt-4o-mini
        """
        await self.config.guild(ctx.guild).model.set(model)
        await ctx.send(f"Model OpenAI został zmieniony na: `{model}`")

    @aiset.command(name="maxhistory")
    async def aiset_maxhistory(self, ctx: commands.Context, count: int):
        """Ustawia maksymalną liczbę wiadomości w historii konwersacji

        Domyślnie: 10 (oznacza 10 par wiadomości user/assistant)
        """
        if count < 1:
            await ctx.send("Liczba musi być większa niż 0.")
            return

        if count > 50:
            await ctx.send("Maksymalna dozwolona wartość to 50.")
            return

        await self.config.guild(ctx.guild).max_history.set(count)
        await ctx.send(f"Maksymalna historia konwersacji została ustawiona na: {count}")

    @aiset.command(name="maxtokens")
    async def aiset_maxtokens(self, ctx: commands.Context, count: int):
        """Ustawia limit max_tokens dla odpowiedzi z OpenAI.

        Domyślnie: 100 (zwykle ~3-4 zdania).
        """
        if count < 1:
            await ctx.send("Liczba musi być większa niż 0.")
            return

        if count > 4096:
            await ctx.send("Maksymalna dozwolona wartość to 4096.")
            return

        await self.config.guild(ctx.guild).max_tokens.set(count)
        await ctx.send(f"max_tokens został ustawiony na: {count}")

    @aiset.command(name="systemprompt")
    async def aiset_systemprompt(self, ctx: commands.Context, *, prompt: str):
        """Ustawia system prompt dla AI

        System prompt określa zachowanie i "osobowość" AI.
        Domyślnie: "Jesteś pomocnym asystentem AI."
        """
        await self.config.guild(ctx.guild).system_prompt.set(prompt)
        await ctx.send(f"System prompt został zmieniony na:\n```{prompt}```")

    @aiset.command(name="show")
    async def aiset_show(self, ctx: commands.Context):
        """Pokazuje aktualną konfigurację"""
        api_key = await self.config.guild(ctx.guild).api_key()
        model = await self.config.guild(ctx.guild).model()
        max_history = await self.config.guild(ctx.guild).max_history()
        max_tokens = await self.config.guild(ctx.guild).max_tokens()
        system_prompt = await self.config.guild(ctx.guild).system_prompt()

        embed = discord.Embed(
            title="Konfiguracja OpenAI Chat",
            color=discord.Color.blue(),
        )
        embed.add_field(
            name="Klucz API",
            value="Ustawiony" if api_key else "Nie ustawiony",
            inline=True,
        )
        embed.add_field(name="Model", value=model, inline=True)
        embed.add_field(name="Max historia", value=str(max_history), inline=True)
        embed.add_field(name="max_tokens", value=str(max_tokens), inline=True)
        embed.add_field(name="System prompt", value=f"```{system_prompt[:100]}...```" if len(system_prompt) > 100 else f"```{system_prompt}```", inline=False)

        await ctx.send(embed=embed)
