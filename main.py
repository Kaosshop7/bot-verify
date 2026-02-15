import discord
from discord import app_commands
from discord.ext import commands, tasks
from discord.ui import Button, View
import datetime
import psutil
import os
import json
import traceback
from keep_alive import keep_alive 

# --- ส่วนตั้งค่า (CONFIG) ---
TOKEN = os.getenv('TOKEN') 
MIN_ACCOUNT_AGE_DAYS = 3      # อายุบัญชีขั้นต่ำ (วัน)
BUTTON_COOLDOWN_SECONDS = 5.0 # ห้ามกดปุ่มรัวๆ ใน 5 วินาที
DATA_FILE = "bot_data.json"   # ชื่อไฟล์สำหรับบันทึกข้อมูล

# --- เริ่มต้นระบบบอท ---
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ตัวแปรเก็บ Cooldown ชั่วคราว
cooldowns = {}

# --- ระบบจัดการไฟล์ JSON (บันทึกข้อมูลกันหาย) ---
def load_data():
    if not os.path.exists(DATA_FILE):
        return {}
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}

def save_data(key, value):
    data = load_data()
    data[key] = value
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def get_data(key):
    data = load_data()
    return data.get(key)

# --- ฟังก์ชันช่วย (HELPER) ---
async def send_reply(interaction, title, description, color=discord.Color.blue(), ephemeral=True):
    """ฟังก์ชันตอบกลับแบบฉลาด (ใช้ followup เพราะเราจะ Defer ก่อนเสมอ)"""
    embed = discord.Embed(title=title, description=description, color=color)
    
    # ดึงรูปโปรไฟล์
    if interaction.user.avatar:
        icon_url = interaction.user.avatar.url
    else:
        icon_url = interaction.user.default_avatar.url
        
    embed.set_footer(text=f"เรียกใช้งานโดย {interaction.user.display_name}", icon_url=icon_url)
    embed.timestamp = discord.utils.utcnow()

    try:
        await interaction.followup.send(embed=embed, ephemeral=ephemeral)
    except Exception as e:
        print(f"❌ ส่งข้อความตอบกลับไม่สำเร็จ: {e}")

def get_color(color_select: str, custom_hex: str):
    if custom_hex:
        try:
            return discord.Color(int(custom_hex.replace("#", ""), 16))
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
    }
    return colors.get(color_select, discord.Color.default())

# --- ⚡ ระบบหลัก: ดักจับการกดปุ่ม (GLOBAL LISTENER) ⚡ ---
# ส่วนนี้สำคัญมาก! ดักจับทุกปุ่มกด แม้บอทจะรีสตาร์ทก็ยังทำงานได้
@bot.event
async def on_interaction(interaction: discord.Interaction):
    # 1. เช็คว่าเป็นปุ่มกดหรือไม่
    if interaction.type != discord.InteractionType.component:
        return

    # 2. เช็ค ID ปุ่มว่าเป็นของระบบ Verify หรือไม่
    custom_id = interaction.data.get('custom_id', '')
    if not custom_id.startswith('verify:'):
        return

    # 3. ✅ ตอบรับทันที! (กัน Error "Interaction Failed")
    try:
        await interaction.response.defer(ephemeral=True)
    except:
        return

    print(f"👉 ผู้ใช้ {interaction.user} กดปุ่ม: {custom_id}")

    # 4. เริ่มกระบวนการตรวจสอบ
    try:
        # เช็ค Cooldown (กันกดรัว)
        user_id = interaction.user.id
        now = datetime.datetime.now().timestamp()
        
        if user_id in cooldowns:
            retry_after = BUTTON_COOLDOWN_SECONDS - (now - cooldowns[user_id])
            if retry_after > 0:
                await send_reply(
                    interaction, 
                    "⏳ ใจเย็นวัยรุ่น!", 
                    f"กรุณารออีก **{retry_after:.1f}** วินาที ค่อยกดใหม่นะ", 
                    discord.Color.orange()
                )
                return
        cooldowns[user_id] = now

        # แกะ Role ID จากปุ่ม
        try:
            role_id = int(custom_id.split(':')[1])
        except ValueError:
             await send_reply(interaction, "❌ ข้อผิดพลาด", "รูปแบบ ID ยศไม่ถูกต้อง", discord.Color.red())
             return

        role = interaction.guild.get_role(role_id)
        user = interaction.user

        if not role:
            await send_reply(interaction, "❌ ข้อผิดพลาด", "ไม่พบยศนี้ในระบบ (อาจถูกลบไปแล้ว)", discord.Color.red())
            return

        # เช็คความปลอดภัย: อายุบัญชี
        account_age = (discord.utils.utcnow() - user.created_at).days
        
        if account_age < MIN_ACCOUNT_AGE_DAYS:
            try:
                await user.kick(reason=f"Anti-Alt: อายุบัญชี {account_age} วัน")
                await send_reply(
                    interaction, 
                    "🚫 เข้าไม่ได้ครับ (Access Denied)", 
                    f"บัญชีของคุณใหม่เกินไป ({account_age} วัน)\nขั้นต่ำต้องมีอายุ: {MIN_ACCOUNT_AGE_DAYS} วัน\n**สถานะ: เตะออก (KICKED)**", 
                    discord.Color.red()
                )
            except discord.Forbidden:
                await send_reply(interaction, "⚠️ แจ้งเตือน", "บัญชีน่าสงสัย แต่บอทไม่มีสิทธิ์เตะ (Check Kick Permission)", discord.Color.orange())
            except Exception as e:
                 await send_reply(interaction, "❌ ข้อผิดพลาด", f"เตะผู้ใช้ไม่ได้: {e}", discord.Color.red())
            return

        # ให้ยศ
        if role in user.roles:
            await send_reply(interaction, "ℹ️ แจ้งเตือน", f"คุณมียศ {role.mention} อยู่แล้วครับ", discord.Color.blue())
        else:
            try:
                await user.add_roles(role)
                await send_reply(
                    interaction, 
                    "✅ เรียบร้อย (Success)", 
                    f"ยืนยันตัวตนสำเร็จ!\nได้รับยศ: {role.mention}", 
                    discord.Color.green()
                )
            except discord.Forbidden:
                await send_reply(interaction, "❌ สิทธิ์ไม่เพียงพอ", "บอทให้ยศนี้ไม่ได้\n(ช่วยลากยศบอท ขึ้นไปไว้สูงกว่ายศที่จะแจกด้วยครับ)", discord.Color.red())
            except Exception as e:
                await send_reply(interaction, "❌ ข้อผิดพลาด", f"เกิดข้อผิดพลาด: {e}", discord.Color.red())

    except Exception as e:
        print(f"❌ System Error: {e}")
        traceback.print_exc()
        await send_reply(interaction, "❌ ระบบขัดข้อง", "เกิดข้อผิดพลาดร้ายแรง โปรดเช็ค Logs", discord.Color.red())

# --- TASKS (วนลูปสถานะ) ---
@tasks.loop(seconds=15)
async def status_task():
    try:
        servers = len(bot.guilds)
        members = sum(guild.member_count for guild in bot.guilds)
        ram = psutil.virtual_memory().percent
        
        statuses = [
            discord.Activity(type=discord.ActivityType.watching, name=f"👥 {members} คน | 🏠 {servers} เซิร์ฟ"),
            discord.Activity(type=discord.ActivityType.playing, name=f"💻 กินแรม: {ram}%"),
            discord.Activity(type=discord.ActivityType.listening, name="/help | /setup_embed")
        ]
        
        current = int(datetime.datetime.now().second / 15) % len(statuses)
        await bot.change_presence(activity=statuses[current])
    except:
        pass

@bot.event
async def on_ready():
    print(f'✅ ล็อกอินในชื่อ: {bot.user}')
    status_task.start()
    try:
        await bot.tree.sync()
        print("✅ ซิงค์คำสั่ง Slash Commands เรียบร้อย!")
    except Exception as e:
        print(f"❌ ซิงค์คำสั่งล้มเหลว: {e}")

# --- คำสั่ง (SLASH COMMANDS) ---

@bot.tree.command(name="ping", description="เช็ค Ping")
async def ping(interaction: discord.Interaction):
    latency = round(bot.latency * 1000)
    await interaction.response.send_message(f"🏓 ปิง! `{latency}ms`", ephemeral=True)

@bot.tree.command(name="help", description="ดูคู่มือคำสั่งทั้งหมด")
async def help_command(interaction: discord.Interaction):
    embed = discord.Embed(title="🤖 คู่มือคำสั่งบอท", color=discord.Color.gold())
    embed.add_field(name="🛠️ แอดมิน", value="`/setup_embed`, `/edit_embed`, `/add_button`", inline=False)
    embed.add_field(name="ℹ️ ทั่วไป", value="`/ping`, `/help`", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="setup_embed", description="สร้างEmbed")
@app_commands.describe(title="หัวข้อ", description="เนื้อหา", color_select="เลือกสีธีม")
@app_commands.choices(color_select=[
    app_commands.Choice(name="เทา (Gray)", value="Default (Gray)"),
    app_commands.Choice(name="แดง (Red)", value="Red"),
    app_commands.Choice(name="เขียว (Green)", value="Green"),
    app_commands.Choice(name="ฟ้า (Blue)", value="Blue"),
    app_commands.Choice(name="เหลือง (Yellow)", value="Yellow"),
    app_commands.Choice(name="ม่วง (Purple)", value="Purple"),
    app_commands.Choice(name="ขาว (White)", value="White"),
    app_commands.Choice(name="ดำ (Black)", value="Black"),
])
async def setup_embed(interaction: discord.Interaction, title: str, description: str, color_select: str = "Default (Gray)", image_url: str = None):
    final_color = get_color(color_select, None)
    embed = discord.Embed(title=title, description=description, color=final_color)
    if image_url: embed.set_image(url=image_url)
    
    await interaction.response.send_message("✅ กำลังสร้างแผงข้อความ...", ephemeral=True)
    msg = await interaction.channel.send(embed=embed)
    
    # 💾 บันทึก ID ลงไฟล์ JSON
    save_data(f"last_embed_{interaction.guild_id}", {"channel_id": msg.channel.id, "message_id": msg.id})
    
    await interaction.followup.send(f"✅ สร้างเรียบร้อย! (บันทึก ID: {msg.id})", ephemeral=True)

@bot.tree.command(name="edit_embed", description="แก้ไข Embed")
@app_commands.describe(new_title="หัวข้อใหม่", new_description="เนื้อหาใหม่")
async def edit_embed(interaction: discord.Interaction, new_title: str = None, new_description: str = None, image_url: str = None):
    # 📂 ดึงข้อมูลจากไฟล์
    data = get_data(f"last_embed_{interaction.guild_id}")
    
    if not data:
        await interaction.response.send_message("❌ ไม่พบประวัติการสร้าง (ไฟล์อาจหาย หรือคุณยังไม่เคยสร้าง)", ephemeral=True)
        return

    try:
        channel = bot.get_channel(data["channel_id"])
        if not channel:
             try:
                channel = await bot.fetch_channel(data["channel_id"])
             except:
                await interaction.response.send_message("❌ หาห้องแชทไม่เจอ", ephemeral=True)
                return

        message = await channel.fetch_message(data["message_id"])
        
        # แก้ไข Embed
        embed = message.embeds[0]
        if new_title: embed.title = new_title
        if new_description: embed.description = new_description
        if image_url: embed.set_image(url=image_url)
        
        await message.edit(embed=embed)
        await interaction.response.send_message("✅ แก้ไขข้อความเรียบร้อย!", ephemeral=True)
        
    except discord.NotFound:
        await interaction.response.send_message("❌ หาข้อความไม่เจอ (อาจถูกลบไปแล้ว)", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"❌ เกิดข้อผิดพลาด: {e}", ephemeral=True)

@bot.tree.command(name="edit_manual", description="แก้ไขข้อความด้วย ID (ใช้กรณีฉุกเฉิน/ไฟล์หาย)")
async def edit_manual(interaction: discord.Interaction, message_id: str, new_title: str = None, new_description: str = None):
    try:
        msg = await interaction.channel.fetch_message(int(message_id))
        if msg.author != bot.user:
            await interaction.response.send_message("❌ บอทแก้ได้เฉพาะข้อความของตัวเองครับ", ephemeral=True)
            return

        embed = msg.embeds[0]
        if new_title: embed.title = new_title
        if new_description: embed.description = new_description
        
        await msg.edit(embed=embed)
        await interaction.response.send_message("✅ แก้ไขเรียบร้อย!", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"❌ เกิดข้อผิดพลาด: {e}", ephemeral=True)

@bot.tree.command(name="add_button", description="เพิ่มปุ่มรับยศ")
@app_commands.choices(style=[
    app_commands.Choice(name="น้ำเงิน", value="1"),
    app_commands.Choice(name="เทา", value="2"),
    app_commands.Choice(name="เขียว", value="3"),
    app_commands.Choice(name="แดง", value="4")
])
async def add_button(interaction: discord.Interaction, role: discord.Role, label: str, style: str = "3", emoji: str = None, message_id: str = None):
    # ลองใช้ ID ล่าสุดถ้า user ไม่ได้ใส่มา
    target_msg_id = message_id
    if not target_msg_id:
        data = get_data(f"last_embed_{interaction.guild_id}")
        if data:
            target_msg_id = data["message_id"]
    
    if not target_msg_id:
        await interaction.response.send_message("❌ กรุณาระบุ Message ID (เพราะไม่พบประวัติล่าสุด)", ephemeral=True)
        return

    try:
        msg = await interaction.channel.fetch_message(int(target_msg_id))
        
        style_map = {"1": discord.ButtonStyle.blurple, "2": discord.ButtonStyle.gray, "3": discord.ButtonStyle.green, "4": discord.ButtonStyle.red}

        # สร้าง View และดึงปุ่มเก่ามาใส่ (ปุ่มเก่าจะได้ไม่หาย)
        view = View(timeout=None)
        if msg.components:
            for comp in msg.components:
                for child in comp.children:
                    if isinstance(child, discord.Button):
                        view.add_item(Button(style=child.style, label=child.label, emoji=child.emoji, custom_id=child.custom_id))
        
        view.add_item(Button(style=style_map.get(style, discord.ButtonStyle.green), label=label, emoji=emoji, custom_id=f"verify:{role.id}"))
        await msg.edit(view=view)
        
        # อัปเดต ID ล่าสุด
        save_data(f"last_embed_{interaction.guild_id}", {"channel_id": msg.channel.id, "message_id": msg.id})
        
        await interaction.response.send_message(f"✅ เพิ่มปุ่มที่ข้อความ ID {msg.id} สำเร็จ!", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"❌ เกิดข้อผิดพลาด: {e}", ephemeral=True)

# --- รันบอท ---
if __name__ == "__main__":
    keep_alive()
    if TOKEN:
        bot.run(TOKEN)
    else:
        print("❌ ข้อผิดพลาด: ไม่พบ TOKEN ใน Environment Variables")
