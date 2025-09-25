import discord
from discord.ext import commands
from discord.ui import View, Button
import random
import json
import os
from dotenv import load_dotenv
import logging
import math
import keep_alive
import asyncio
import time
import datetime

load_dotenv()
TOKEN = os.getenv('TOKEN')
BACKUP_USER_ID = os.getenv('BACKUP_USER_ID')

if not TOKEN:
    print("❌ 錯誤：找不到 TOKEN 環境變數")
    exit(1)
if not BACKUP_USER_ID:
    print("❌ 錯誤：找不到 BACKUP_USER_ID 環境變數")
    exit(1)

print(f"✅ Token 已安全載入")
print(f"✅ Backup User ID 已載入: {BACKUP_USER_ID}")

# Global cooldown tracker
last_backup_time = 0  # Tracks last backup timestamp
BACKUP_COOLDOWN = 60  # 60 seconds cooldown


# 初始化 prizes 變量 - 確保是乾淨的字典
prizes_data = {}  # 改名避免衝突

# 載入之前的資料
def load_prizes():
    global prizes_data
    if os.path.exists('prizes_data.json'):
        try:
            with open('prizes_data.json', 'r', encoding='utf-8') as f:
                loaded_data = json.load(f)
                # 嚴格驗證資料格式
                prizes_data = {}
                for name, data in loaded_data.items():
                    if (isinstance(name, str) and 
                        isinstance(data, dict) and 
                        "participants" in data and 
                        "winners" in data and
                        isinstance(data["participants"], list) and
                        isinstance(data["winners"], int)):
                        prizes_data[name] = {
                            "participants": data["participants"],
                            "winners": data["winners"]
                        }
                print(f"✅ 已載入 {len(prizes_data)} 個獎品資料")
        except Exception as e:
            print(f"❌ 載入資料失敗: {e}")
            prizes_data = {}
            print("ℹ️ 已重置為空資料")
    else:
        print("ℹ️ 沒有找到之前的資料，從頭開始")



async def send_backup_to_user():
    global last_backup_time
    try:
        # Calculate time since last backup
        current_time = time.time()
        time_since_last_backup = current_time - last_backup_time
        
        # If within cooldown, wait until 60 seconds have passed
        if time_since_last_backup < BACKUP_COOLDOWN:
            wait_time = BACKUP_COOLDOWN - time_since_last_backup
            logging.debug(f"備份冷卻中，等待 {wait_time:.2f} 秒")
            await asyncio.sleep(wait_time)
        
        # Update last backup time
        last_backup_time = time.time()
        
        json_path = 'prizes_data.json'
        if not os.path.exists(json_path):
            logging.error("備份失敗：prizes_data.json 不存在")
            return
        
        user = await bot.fetch_user(int(BACKUP_USER_ID))
        if not user:
            logging.error(f"備份失敗：找不到用戶 ID {BACKUP_USER_ID}")
            return

        # Send file via DM with timestamp
        with open(json_path, 'rb') as f:
            await user.send(f"📤 自動備份 prizes_data.json ({datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')})", 
                          file=discord.File(f, 'prizes_data_backup.json'))
        logging.debug(f"成功發送備份到用戶 {BACKUP_USER_ID}")
    except discord.errors.Forbidden:
        logging.error(f"備份失敗：無法向用戶 {BACKUP_USER_ID} 發送 DM（可能被封鎖或未啟用 DM）")
    except Exception as e:
        logging.error(f"備份失敗：{e}")



# 保存資料
def save_prizes():
    global prizes_data
    try:
        with open('prizes_data.json', 'w', encoding='utf-8') as f:
            json.dump(prizes_data, f, ensure_ascii=False, indent=2)
        print(f"💾 已保存 {len(prizes_data)} 個獎品資料")
        # Send backup to user asynchronously
        bot.loop.create_task(send_backup_to_user())
    except Exception as e:
        print(f"❌ 保存資料失敗: {e}")

# 載入資料
load_prizes()

intents = discord.Intents.default()
intents.message_content = True
intents.members = True  # 需要成員意圖

bot = commands.Bot(command_prefix='!', intents=intents)

class LeavePrizeButton(Button):
    def __init__(self, prize_name):
        super().__init__(label=f"退出「{prize_name}」抽獎", style=discord.ButtonStyle.danger, custom_id=f"leave_{prize_name}")
        self.prize_name = prize_name

    async def callback(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)

        if self.prize_name in prizes_data and user_id in prizes_data[self.prize_name]["participants"]:
            prizes_data[self.prize_name]["participants"].remove(user_id)
            save_prizes()
            await interaction.response.send_message(f"✅ 你已退出「{self.prize_name}」抽獎。", ephemeral=True)
        else:
            await interaction.response.send_message(f"⚠️ 你尚未參加「{self.prize_name}」，無法退出。", ephemeral=True)

class PrizeJoinButton(Button):
    def __init__(self, prize_name):
        super().__init__(label=f"參加「{prize_name}」", style=discord.ButtonStyle.primary, custom_id=f"join_{prize_name}")
        self.prize_name = prize_name

    async def callback(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        
        if self.prize_name not in prizes_data:
            await interaction.response.send_message(f"❌ 「{self.prize_name}」已不存在。", ephemeral=True)
            return
        
        if user_id in prizes_data[self.prize_name]["participants"]:
            view = View()
            view.add_item(LeavePrizeButton(self.prize_name))
            await interaction.response.send_message(f"⚠️ 你已參加過「{self.prize_name}」的抽獎。", ephemeral=True, view=view)
            return
        
        prizes_data[self.prize_name]["participants"].append(user_id)
        save_prizes()
        await interaction.response.send_message(f"✅ 你已成功參加「{self.prize_name}」的抽獎！", ephemeral=True)

class AllParticipantsButton(Button):
    def __init__(self):
        super().__init__(label="查看所有參加者清單", style=discord.ButtonStyle.secondary, custom_id="list_all")

    async def callback(self, interaction: discord.Interaction):
        if not prizes_data:
            await interaction.response.send_message("📭 目前沒有獎品。", ephemeral=True)
            return
        
        try:
            # 立即延遲回應，避免交互超時
            await interaction.response.defer(ephemeral=True)

            # 緩存當前伺服器成員
            guild = interaction.guild
            member_cache = {member.id: member for member in guild.members}
            logging.debug(f"已緩存 {len(member_cache)} 個成員")

            prize_items = list(prizes_data.items())
            page_size = 5  # 每頁最多 5 項獎品，減少第一頁處理時間
            total_pages = math.ceil(len(prize_items) / page_size)

            for page in range(total_pages):
                embed = discord.Embed(
                    title=f"🎁 所有獎品參加者清單 (頁 {page + 1}/{total_pages})",
                    description="以下是各獎品的參加者名單：",
                    color=discord.Color.red()
                )
                start_idx = page * page_size
                end_idx = min(start_idx + page_size, len(prize_items))
                
                for prize, info in prize_items[start_idx:end_idx]:
                    participant_names = []
                    for participant_id in info["participants"]:
                        try:
                            user_id = int(participant_id)
                            # 優先使用緩存
                            user = member_cache.get(user_id)
                            if not user:
                                try:
                                    user = await guild.fetch_member(user_id)
                                    member_cache[user_id] = user
                                    logging.debug(f"fetch_member 成功: {user_id}")
                                except discord.NotFound:
                                    user = None
                                except Exception as e:
                                    logging.error(f"fetch_member 失敗: {e}")
                            if user:
                                participant_names.append(user.display_name)
                            else:
                                participant_names.append(f"ID:{participant_id}")
                        except ValueError:
                            participant_names.append(participant_id)
                    
                    participants_str = ", ".join(participant_names) if participant_names else "📭 尚無參加者"
                    embed.add_field(
                        name=f"📦 {prize}（{info['winners']}人）",
                        value=f"👥 參加者：{participants_str}",
                        inline=False
                    )
                
                embed.set_footer(text="請遵守抽獎規則！")
                # 第一頁使用 followup（因已 defer），後續頁繼續使用 followup
                await interaction.followup.send(embed=embed, ephemeral=True)
                # 添加延遲，避免 API 限制
                await asyncio.sleep(0.5)

        except Exception as e:
            logging.error(f"AllParticipantsButton 錯誤: {e}")
            await interaction.followup.send(f"❌ 顯示參加者清單失敗：{e}", ephemeral=True)

# 設置日誌
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

# 定義內建類型（避免被覆蓋的 list 影響）
_builtin_list = list
_builtin_dict = dict
_builtin_str = str
_builtin_int = int

@bot.command()
@commands.has_permissions(administrator=True)
async def show_prizes(ctx):
    global prizes_data
    try:
        content = _builtin_list(prizes_data.keys())[:5] if isinstance(prizes_data, _builtin_dict) else prizes_data
        logging.debug(f"執行 !show_prizes, prizes_data 類型: {type(prizes_data)}, 內容: {content}")
    except Exception as e:
        logging.error(f"記錄 prizes_data 失敗: {e}")
    if not isinstance(prizes_data, _builtin_dict):
        logging.error(f"prizes_data 類型錯誤: {type(prizes_data)}, 內容: {prizes_data}")
        embed = discord.Embed(
            title="❌ 錯誤",
            description="獎品資料異常，請聯繫管理員檢查 prizes_data.json。",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
        return
    if not prizes_data:
        embed = discord.Embed(
            title="📭 無獎品",
            description="目前沒有獎品。請先用 !add_prize 新增。",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
        return

    # 分頁設定：每頁 12 項
    page_size = 12
    prize_items = _builtin_list(prizes_data.items())
    total_pages = math.ceil(len(prize_items) / page_size)  # 33 項分 3 頁（12、12、9）

    # 發送每頁的嵌入訊息
    for page in range(total_pages):
        view = View(timeout=None)  # 每頁獨立的 View
        start_idx = page * page_size
        end_idx = min(start_idx + page_size, len(prize_items))
        embed = discord.Embed(
            title=f"🎁 焰獄拍賣會獎品清單 (頁 {page + 1}/{total_pages})",
            description="請點擊下方按鈕參加你想要的獎品抽獎：",
            color=discord.Color.red()
        )
        try:
            logging.debug(f"生成頁 {page + 1}: 顯示獎品索引 {start_idx} 到 {end_idx}, 項目: {[name for name, _ in prize_items[start_idx:end_idx]]}")
            for prize, info in prize_items[start_idx:end_idx]:
                embed.add_field(
                    name=f"📦 {prize}",
                    value=f"**得獎人數**：{info['winners']}\n**參加者**：{len(info['participants'])} 人",
                    inline=True
                )
                view.add_item(PrizeJoinButton(prize))
        except Exception as e:
            logging.error(f"生成嵌入欄位失敗 (頁 {page + 1}): {e}")
            embed.add_field(
                name="❌ 錯誤",
                value="無法顯示獎品清單，請聯繫管理員。",
                inline=False
            )
        
        # 最後一頁添加「查看所有參加者」按鈕
        if page == total_pages - 1:
            view.add_item(AllParticipantsButton())
        
        embed.set_footer(text="請遵守抽獎規則！")
        await ctx.send(embed=embed, view=view)

@bot.event
async def on_ready():
    print(f'✅ Bot 已登入：{bot.user}')
    print(f"DEBUG: Bot 在 {len(bot.guilds)} 個伺服器中")
    save_prizes()

@bot.command()
@commands.has_permissions(administrator=True)
async def add_prize(ctx, *, prize_input):
    global prizes_data
    added = []
    existed = []
    for item in [i.strip() for i in prize_input.split(',') if i.strip()]:
        if ':' in item:
            name, count = item.split(':', 1)
            name = name.strip()
            try:
                count = int(count.strip())
            except ValueError:
                count = 1
        else:
            name = item
            count = 1

        if name in prizes_data:
            existed.append(name)
        else:
            prizes_data[name] = {"participants": [], "winners": count}
            added.append(f"{name}（{count}人）")

    msg = []
    if added:
        msg.append("🎁 已新增獎品：" + ", ".join(added))
    if existed:
        msg.append("⚠️ 已存在：" + ", ".join(existed))
    await ctx.send("\n".join(msg) if msg else "請輸入要新增的獎品名稱。")
    
    if added:
        save_prizes()

@bot.command()
@commands.has_permissions(administrator=True)
async def prizes_list(ctx):
    if not prizes_data:
        await ctx.send("📭 目前沒有獎品。")
    else:
        msg = ["🎁 獎品清單："]
        for prize, info in prizes_data.items():
            msg.append(f"\n📦 {prize}（{info['winners']}人）")
            if info["participants"]:
                participant_names = []
                for participant_id in info["participants"]:
                    try:
                        user_id = int(participant_id)
                        user = ctx.guild.get_member(user_id)
                        if user:
                            participant_names.append(user.display_name)
                        else:
                            participant_names.append(f"ID:{participant_id}")
                    except ValueError:
                        participant_names.append(participant_id)
                
                msg.append(f"👥 參加者：{', '.join(participant_names)}")
            else:
                msg.append("📭 尚無參加者")
        await ctx.send("\n".join(msg))

@bot.command(name="list")
@commands.has_permissions(administrator=True)
async def prize_participants(ctx, *, prize_names):
    names = [n.strip() for n in prize_names.split(',') if n.strip()]
    msg = []
    for name in names:
        if name not in prizes_data:
            msg.append(f"❌ 沒有這個獎品：「{name}」")
        elif not prizes_data[name]["participants"]:
            msg.append(f"📭 「{name}」目前沒有人參加。")
        else:
            participant_names = []
            for participant_id in prizes_data[name]["participants"]:
                try:
                    user_id = int(participant_id)
                    user = ctx.guild.get_member(user_id)
                    if user:
                        participant_names.append(user.display_name)
                    else:
                        participant_names.append(f"ID:{participant_id}")
                except ValueError:
                    participant_names.append(participant_id)
            
            participants_str = ", ".join(participant_names)
            msg.append(f"👥 「{name}」的參加者：{participants_str}")
    await ctx.send("\n".join(msg) if msg else "請輸入要查詢的獎品名稱。")

@bot.command()
@commands.has_permissions(administrator=True)
async def draw(ctx):
    global prizes_data
    
    print(f"DEBUG: prizes_data 類型: {type(prizes_data)}")
    print(f"DEBUG: prizes_data 內容: {prizes_data}")
    
    if not isinstance(prizes_data, dict):
        await ctx.send("❌ 獎品資料異常，請重新啟動 Bot")
        return
    
    if not prizes_data:
        await ctx.send("📭 目前沒有獎品。")
        return

    prize_names = list(prizes_data.keys())
    prize_items = list(prizes_data.items())
    page_size = 10  # 每頁最多 10 項獎品
    total_pages = math.ceil(len(prize_items) / page_size)
    fetch_count = 0  # 計數 fetch_member 調用次數
    member_cache = {member.id: member for member in ctx.guild.members}
    logging.debug(f"已緩存 {len(member_cache)} 個成員（guild.members）")

    for page in range(total_pages):
        embed = discord.Embed(
            title=f"🎉 抽獎結果 (頁 {page + 1}/{total_pages})",
            description="以下是本次抽獎的得獎名單：",
            color=discord.Color.red()
        )
        start_idx = page * page_size
        end_idx = min(start_idx + page_size, len(prize_items))
        
        for name, info in prize_items[start_idx:end_idx]:
            participants = info.get("participants", [])
            winner_count = info.get("winners", 1)
            print(f"DEBUG: 處理獎品: {name}, 參加者: {len(participants)}, 得主數: {winner_count}")
            
            if not participants:
                embed.add_field(
                    name=f"📦 {name}（{winner_count}人）",
                    value="😢 沒有人參加，無法抽獎。",
                    inline=False
                )
            else:
                actual_winners = min(winner_count, len(participants))
                try:
                    winners = random.sample(participants, actual_winners)
                    print(f"DEBUG: 抽中: {winners}")
                    
                    mention_list = []
                    for participant_id in winners:
                        print(f"DEBUG: 處理參加者: {participant_id} (類型: {type(participant_id)})")
                        user = None
                        try:
                            user_id = int(participant_id)
                            print(f"DEBUG: 解析為 ID: {user_id}")
                            user = member_cache.get(user_id)
                            if not user:
                                if fetch_count < 50:  # 限制最大 fetch_member 調用次數
                                    try:
                                        user = await ctx.guild.fetch_member(user_id)
                                        member_cache[user_id] = user
                                        print(f"DEBUG: fetch_member 成功")
                                        fetch_count += 1
                                        if fetch_count % 10 == 0:
                                            await asyncio.sleep(1.0)
                                    except Exception as e:
                                        print(f"DEBUG: fetch_member 失敗: {e}")
                            if user:
                                print(f"DEBUG: 成功找到用戶: {user.display_name} (ID: {user.id})")
                                mention_list.append(user.mention)
                            else:
                                print(f"DEBUG: 找不到用戶 ID {user_id}")
                                mention_list.append(f"**ID:{participant_id}**")
                        except ValueError:
                            print(f"DEBUG: 非數字 ID，視為舊資料: {participant_id}")
                            for member in ctx.guild.members:
                                if (member.display_name == participant_id or 
                                    member.name == participant_id):
                                    user = member
                                    mention_list.append(user.mention)
                                    print(f"DEBUG: 名稱匹配成功: {user.display_name}")
                                    break
                            else:
                                mention_list.append(f"**@{participant_id}**")
                    
                    if len(winners) == 1:
                        winner_mentions = mention_list[0]
                    elif len(winners) > 3:
                        winner_mentions = ", ".join(mention_list[:3]) + " 等..."
                    else:
                        winner_mentions = ", ".join(mention_list[:-1]) + f" 和 {mention_list[-1]}"
                    
                    field_value = f"🎉 恭喜 {winner_mentions} 獲得！"
                    if len(field_value) > 1024:
                        field_value = field_value[:1020] + "..."
                    embed.add_field(
                        name=f"📦 {name}（{actual_winners}人）",
                        value=field_value,
                        inline=False
                    )
                except ValueError as e:
                    print(f"DEBUG: 抽獎錯誤: {e}")
                    embed.add_field(
                        name=f"📦 {name}（{winner_count}人）",
                        value="😢 參加者不足以抽出指定數量的得主。",
                        inline=False
                    )
            
            if name in prizes_data:
                del prizes_data[name]
                print(f"DEBUG: 已刪除獎品 {name}")
        
        # 檢查嵌入大小
        embed_size = len(str(embed))
        if embed_size > 6000:
            logging.warning(f"抽獎頁 {page + 1} 嵌入過大: {embed_size} 字元")
            embed = discord.Embed(
                title=f"🎉 抽獎結果 (頁 {page + 1}/{total_pages})",
                description="部分得獎名單過長，無法顯示完整內容。",
                color=discord.Color.red()
            )
            embed.add_field(
                name="⚠️ 警告",
                value="請減少每項獎品的得獎者數量或聯繫管理員。",
                inline=False
            )
        
        embed.set_footer(text="請遵守抽獎規則！")
        await ctx.send(embed=embed)
        logging.debug(f"發送抽獎結果頁 {page + 1}, 字元數: {embed_size}")
        if page < total_pages - 1:
            await asyncio.sleep(0.2)  # 頁面間延遲
    
    save_prizes()
    print("DEBUG: 抽獎完成")

@bot.command()
@commands.cooldown(1, 60, commands.BucketType.user)
async def 啊偉(ctx):
    responses = [
        "啊～～～～～～偉～～～～～～～又在睡午覺啦？快醒醒！",
        "啊～～～～～～偉～～～～～～～手機又掉馬桶裡了嗎？",
        "啊～～～～～～偉～～～～～～～跑去哪偷吃零食啦？",
        "啊～～～～～～偉～～～～～～～你的Wi-Fi又斷線了吧？",
        "啊～～～～～～偉～～～～～～～別躲啦，聚會開始囉！",
        "啊～～～～～～偉～～～～～～～還在跟NPC吵架嗎？",
        "啊～～～～～～偉～～～～～～～快來，派對缺你不行！",
        "啊～～～～～～偉～～～～～～～是不是又迷路到隔壁伺服器？",
        "啊～～～～～～偉～～～～～～～別裝酷啦，大家都在等你！",
        "啊～～～～～～偉～～～～～～～你的傳說級拖延症又發作了？"
    ]
    await ctx.send(random.choice(responses))

@bot.event
async def on_member_join(member):
    welcome_message = "新成員進來請把名字改成遊戲裡的，方便識別，改完後請脫。"
    # Option 1: Send to a specific channel (replace CHANNEL_ID with your channel ID)
    channel = member.guild.get_channel(1301173686899838988)  # Replace CHANNEL_ID with actual ID
    if channel:
        await channel.send(f"{member.mention} {welcome_message}")
    else:
        print(f"DEBUG: Welcome channel (ID: 1301173686899838988) not found")

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ 你沒有權限使用這個指令。")
    else:
        print(f"DEBUG: 指令錯誤: {error}")
        raise error

@bot.event
async def on_disconnect():
    save_prizes()
    print("👋 Bot 斷線，已保存資料")

@bot.command()
@commands.has_permissions(administrator=True)
async def backup(ctx):
    global prizes_data
    if not isinstance(prizes_data, _builtin_dict):
        logging.error(f"prizes_data 類型錯誤: {type(prizes_data)}, 內容: {prizes_data}")
        await ctx.send("❌ 獎品資料異常，無法備份。")
        return
    try:
        # 確認檔案存在
        json_path = 'prizes_data.json'
        if not os.path.exists(json_path):
            logging.error("prizes_data.json 不存在")
            await ctx.send("❌ 找不到 prizes_data.json 檔案。")
            return
        
        # 發送檔案附件
        with open(json_path, 'rb') as f:
            await ctx.send("✅ 備份檔案：", file=discord.File(f, 'prizes_data_backup.json'))
        
        logging.debug(f"備份執行成功，用戶: {ctx.author.id}, 檔案大小: {os.path.getsize(json_path)} bytes")
    except Exception as e:
        logging.error(f"備份錯誤: {e}")
        await ctx.send(f"❌ 備份失敗：{e}")

@bot.command()
@commands.has_permissions(administrator=True)
async def restore(ctx):
    global prizes_data
    if not ctx.message.attachments:
        await ctx.send("❌ 請上傳 prizes_data.json 檔案以進行還原。")
        return
    try:
        # 獲取第一個附件
        attachment = ctx.message.attachments[0]
        if not attachment.filename.endswith('.json'):
            await ctx.send("❌ 請上傳 JSON 格式的檔案。")
            return
        
        # 下載並讀取檔案內容
        file_content = await attachment.read()
        prizes_data = json.loads(file_content.decode('utf-8'))
        
        # 驗證資料格式
        if not isinstance(prizes_data, _builtin_dict):
            logging.error(f"還原資料格式錯誤: {type(prizes_data)}")
            await ctx.send("❌ 還原檔案格式錯誤，必須是 JSON 物件。")
            return
        for name, data in prizes_data.items():
            if not (isinstance(name, _builtin_str) and 
                    isinstance(data, _builtin_dict) and
                    "participants" in data and 
                    isinstance(data["participants"], _builtin_list) and
                    "winners" in data and 
                    isinstance(data["winners"], _builtin_int)):
                logging.error(f"還原資料結構無效: {name}, data: {data}")
                await ctx.send("❌ 還原檔案結構無效，請檢查格式。")
                return
        
        # 保存到檔案
        with open('prizes_data.json', 'w', encoding='utf-8') as f:
            json.dump(prizes_data, f, ensure_ascii=False, indent=2)
        
        await ctx.send("✅ 資料還原成功！請使用 !show_prizes 檢查。")
        logging.debug(f"還原成功，用戶: {ctx.author.id}, 獎品數: {len(prizes_data)}")
    except Exception as e:
        logging.error(f"還原錯誤: {e}")
        await ctx.send(f"❌ 還原失敗：{e}")

keep_alive.keep_alive()
bot.run(TOKEN)