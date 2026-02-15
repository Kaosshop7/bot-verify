import discord
from discord import app_commands
from discord.ext import commands, tasks
from discord.ui import Button, View
import datetime
import psutil
import os
from keep_alive import keep_alive

TOKEN = os.getenv('TOKEN') 
MIN_ACCOUNT_AGE_DAYS = 3  
BUTTON_COOLDOWN_SECONDS = 5.0 

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

async def send_embed(interaction, title, description, color=discord.Color.blue(), ephemeral=True):
    embed = discord.Embed(title=title, description=description, color=color)
    if interaction.user.avatar:
        embed.set_footer(text=f"Requested by {interaction.user.display_name}", icon_url=interaction.user.display_avatar.url)
    else:
        embed.set_footer(text=f"Requested by {interaction.user.display_name}")
    embed.timestamp = discord.utils.utcnow()
    await interaction.response.send_message(embed=embed, ephemeral=ephemeral)

def get_color(color_select: str, custom_hex: str):
    if custom_hex:
        try:
            clean_hex = custom_hex.replace("#", "")
            return discord.Color(int(clean_hex, 16))
        except:
            pass
    
    colors = {
        "Default (Gray)": discord.Color.default(),
        "Red": discord.Color.red(),
        "Green": discord.Color.green(),
        "Blue": discord.Color.blue(),
        "Yellow": discord.Color.gold(),
        "Purple": discord.Color.purple(),
        "White": discord.Color.from_rgb(255, 255, 255),
        "Black": discord.Color.from_rgb(0, 0, 0),
        "Pink": discord.Color.from_rgb(255, 105, 180),
        "Orange": discord.Color.orange()
    }
    return colors.get(color_select, discord.Color.default())

class VerifyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.cooldowns = {}

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        user_id = interaction.user.id
        now = datetime.datetime.now().timestamp()
        
        if user_id in self.cooldowns:
            retry_after = BUTTON_COOLDOWN_SECONDS - (now - self.cooldowns[user_id])
            if retry_after > 0:
                await send_embed(
                    interaction, 
                    "⏳ ใจเย็นนะครับ (Cooldown)", 
                    f"กรุณารออีก **{retry_after:.1f}** วินาที ก่อนกดใหม่", 
                    discord.Color.orange()
                )
                return False

        self.cooldowns[user_id] = now
        
        custom_id = interaction.data.get('custom_id', '')
        if custom_id.startswith('verify:'):
            await self.handle_verify(interaction, custom_id)
            return False 
        return True

    async def handle_verify(self, interaction: discord.Interaction, custom_id: str):
        try:
            role_id = int(custom_id.split(':')[1])
            role = interaction.guild.get_role(role_id)
            user = interaction.user

            if not role:
                await send_embed(interaction, "❌ Error", "ไม่พบยศนี้ในระบบ (อาจถูกลบไปแล้ว)", discord.Color.red())
                return

            account_age = (discord.utils.utcnow() - user.created_at).days

            if account_age < MIN_ACCOUNT_AGE_DAYS:
                try:
                    await user.kick(reason=f"Anti-Alt: Account age {account_age} days")
                    await send_embed(
                        interaction, 
                        "🚫 Access Denied", 
                        f"บัญชีของคุณใหม่เกินไป ({account_age} วัน)\nต้องการอย่างน้อย {MIN_ACCOUNT_AGE_DAYS} วัน\n**สถานะ: KICKED**", 
                        discord.Color.red()
                    )
                except:
                    await send_embed(interaction, "⚠️ Warning", "บัญชีเสี่ยง แต่บอทไม่มีสิทธิ์ Kick", discord.Color.orange())
                return

            if role in user.roles:
                await send_embed(interaction, "ℹ️ Info", f"คุณมียศ {role.mention} อยู่แล้ว", discord.Color.blue())
            else:
                try:
                    await user.add_roles(role)
                    await send_embed(
                        interaction, 
                        "✅ Verification Success", 
                        f"ยืนยันตัวตนสำเร็จ!\nได้รับยศ: {role.mention}", 
                        discord.Color.green()
                    )
                except discord.Forbidden:
                    await send_embed(interaction, "❌ Permission Error", "บอทไม่มีสิทธิ์ให้ยศนี้ (โปรดเช็คลำดับยศ)", discord.Color.red())
        
        except Exception as e:
            await send_embed(interaction, "❌ System Error", f"{e}", discord.Color.red())

@tasks.loop(seconds=15)
async def status_task():
    servers = len(bot.guilds)
    members = sum(guild.member_count for guild in bot.guilds)
    ram = psutil.virtual_memory().percent
    
    statuses = [
        discord.Activity(type=discord.ActivityType.watching, name=f"👥 {members} Users | 🏠 {servers} Servers"),
        discord.Activity(type=discord.ActivityType.playing, name=f"💻 RAM Usage: {ram}%"),
        discord.Activity(type=discord.ActivityType.listening, name="/help | /setup_embed")
    ]
    
    current = int(datetime.datetime.now().second / 15) % len(statuses)
    await bot.change_presence(activity=statuses[current])

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}')
    status_task.start()
    bot.add_view(VerifyView())
    try:
        await bot.tree.sync()
        print("Slash commands synced!")
    except Exception as e:
        print(e)


@bot.tree.command(name="ping", description="เช็คค่าความหน่วง")
async def ping(interaction: discord.Interaction):
    latency = round(bot.latency * 1000)
    color = discord.Color.green() if latency < 100 else discord.Color.orange()
    await send_embed(interaction, "🏓 Pong!", f"**Latency:** `{latency}ms`\n**API Status:** Online", color)

@bot.tree.command(name="help", description="ดูรายการคำสั่งทั้งหมด")
async def help_command(interaction: discord.Interaction):
    embed = discord.Embed(title="🤖 Bot Commands Manual", description="รายการคำสั่งทั้งหมดที่ใช้งานได้", color=discord.Color.gold())
    embed.add_field(name="🛠️ Admin Commands", value="`/setup_embed` - สร้างแผงรับยศ\n`/add_button` - เพิ่มปุ่มรับยศใส่ข้อความเดิม", inline=False)
    embed.add_field(name="ℹ️ General", value="`/ping` - เช็คค่าปิง\n`/help` - ดูหน้านี้", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="setup_embed", description="สร้างEmbed")
@app_commands.describe(title="หัวข้อหลัก", description="เนื้อหา", color_select="เลือกสี", custom_hex="โค้ดสี Hex", image_url="รูป Banner", thumbnail_url="รูปเล็ก", footer="ข้อความด้านล่าง")
@app_commands.choices(color_select=[
    app_commands.Choice(name="Discord Dark", value="Default (Gray)"),
    app_commands.Choice(name="Red 🔴", value="Red"),
    app_commands.Choice(name="Green 🟢", value="Green"),
    app_commands.Choice(name="Blue 🔵", value="Blue"),
    app_commands.Choice(name="Yellow 🟡", value="Yellow"),
    app_commands.Choice(name="Purple 🟣", value="Purple"),
    app_commands.Choice(name="White ⚪", value="White"),
    app_commands.Choice(name="Black ⚫", value="Black"),
])
async def setup_embed(interaction: discord.Interaction, title: str, description: str, color_select: str = "Default (Gray)", custom_hex: str = None, image_url: str = None, thumbnail_url: str = None, footer: str = None):
    final_color = get_color(color_select, custom_hex)
    public_embed = discord.Embed(title=title, description=description, color=final_color)
    if image_url: public_embed.set_image(url=image_url)
    if thumbnail_url: public_embed.set_thumbnail(url=thumbnail_url)
    if footer: public_embed.set_footer(text=footer)
    await interaction.channel.send(embed=public_embed)
    await send_embed(interaction, "✅ Success", "สร้าง Embed เรียบร้อยแล้ว!", discord.Color.green())

@bot.tree.command(name="add_button", description="เพิ่มปุ่มรับยศ")
@app_commands.describe(message_id="ID ข้อความ", role="ยศที่แจก", label="ชื่อปุ่ม", emoji="ไอคอน", style="สีปุ่ม")
@app_commands.choices(style=[
    app_commands.Choice(name="Blue (Primary)", value="1"),
    app_commands.Choice(name="Gray (Secondary)", value="2"),
    app_commands.Choice(name="Green (Success)", value="3"),
    app_commands.Choice(name="Red (Danger)", value="4")
])
async def add_button(interaction: discord.Interaction, message_id: str, role: discord.Role, label: str, emoji: str = None, style: str = "3"):
    try:
        msg_id_int = int(message_id)
        message = await interaction.channel.fetch_message(msg_id_int)
        if message.author != bot.user:
            await send_embed(interaction, "❌ Error", "บอทแก้ไขได้เฉพาะข้อความของตัวเองเท่านั้น", discord.Color.red())
            return
        
        style_map = {"1": discord.ButtonStyle.blurple, "2": discord.ButtonStyle.gray, "3": discord.ButtonStyle.green, "4": discord.ButtonStyle.red}
        new_button = Button(style=style_map.get(style, discord.ButtonStyle.green), label=label, emoji=emoji, custom_id=f"verify:{role.id}")
        
        view = View(timeout=None)
        if message.components:
            for component in message.components:
                if isinstance(component, discord.ActionRow):
                    for child in component.children:
                        if isinstance(child, discord.Button):
                            old_btn = Button(style=child.style, label=child.label, emoji=child.emoji, url=child.url, disabled=child.disabled, custom_id=child.custom_id)
                            view.add_item(old_btn)
        view.add_item(new_button)
        await message.edit(view=view)
        await send_embed(interaction, "✅ Button Added", f"เพิ่มปุ่ม **{label}** เรียบร้อย!", discord.Color.green())
    except Exception as e:
        await send_embed(interaction, "❌ Error", f"{e}", discord.Color.red())

if __name__ == "__main__":
    keep_alive()
    
    if TOKEN:
        bot.run(TOKEN)
    else:
        print("❌ Error: ไม่พบ TOKEN ใน Environment Variables")
