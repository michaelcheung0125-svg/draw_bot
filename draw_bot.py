import discord
from discord.ext import commands
from discord.ui import View, Button
import random
import json
import os
from dotenv import load_dotenv
import keep_alive
import logging
import base64  # 用來編碼檔案內容，避免 Discord 限制


# 載入環境變數
load_dotenv()

# 安全讀取 Token
TOKEN = os.getenv('TOKEN')

if not TOKEN:
    print("❌ 錯誤：找不到 TOKEN 環境變數")
    exit(1)

print(f"✅ Token 已安全載入")

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

# 保存資料
def save_prizes():
    global prizes_data
    try:
        with open('prizes_data.json', 'w', encoding='utf-8') as f:
            json.dump(prizes_data, f, ensure_ascii=False, indent=2)
        print(f"💾 已保存 {len(prizes_data)} 個獎品資料")
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
        
        msg = ["🎁 所有獎品參加者清單："]
        guild = interaction.guild
        for prize, info in prizes_data.items():
            msg.append(f"\n📦 {prize}（{info['winners']}人）")
            if info["participants"]:
                participant_names = []
                for participant_id in info["participants"]:
                    try:
                        user_id = int(participant_id)
                        user = guild.get_member(user_id)
                        if user:
                            participant_names.append(user.display_name)
                        else:
                            participant_names.append(f"ID:{participant_id}")
                    except ValueError:
                        participant_names.append(participant_id)
                
                msg.append(f"👥 參加者：{', '.join(participant_names)}")
            else:
                msg.append("📭 尚無參加者")
        await interaction.response.send_message("\n".join(msg), ephemeral=True)


# 設置日誌
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

class PaginationView(View):
    def __init__(self, prize_dict, page_size=12):  # 調整為 12 項/頁
        super().__init__(timeout=300)  # 5 分鐘超時
        if not isinstance(prize_dict, dict):
            logging.error(f"PaginationView 初始化失敗: prize_dict 類型為 {type(prize_dict)}, 內容: {prize_dict}")
            raise ValueError("prize_dict 必須是字典")
        self.prize_dict = prize_dict
        self.page_size = page_size
        self.current_page = 0
        self.total_pages = (len(prize_dict) + page_size - 1) // page_size if prize_dict else 1
        logging.debug(f"初始化 PaginationView: 總獎品數 {len(prize_dict)}, 總頁數 {self.total_pages}, prize_dict: {[k for k in prize_dict.keys()][:5]}...")
        self.update_buttons()

    def update_buttons(self):
        self.clear_items()
        # 參加抽獎按鈕（當前頁的獎品）
        start_idx = self.current_page * self.page_size
        end_idx = min(start_idx + self.page_size, len(self.prize_dict))
        try:
            prize_keys = [k for k in self.prize_dict.keys()]  # 使用列表推導式避免影子問題
            logging.debug(f"update_buttons: prize_keys 類型: {type(prize_keys)}, 長度: {len(prize_keys)}, 前5項: {prize_keys[:5]}")
            for prize in prize_keys[start_idx:end_idx]:
                self.add_item(PrizeJoinButton(prize))
        except Exception as e:
            logging.error(f"生成按鈕失敗: {e}, prize_dict 類型: {type(self.prize_dict)}, keys 類型: {type(self.prize_dict.keys())}")
            raise
        # 底部的控制按鈕（上一頁、下一頁、查看所有參加者）
        prev_button = Button(label="上一頁", style=discord.ButtonStyle.secondary, disabled=self.current_page == 0)
        prev_button.callback = self.prev_page
        self.add_item(prev_button)
        next_button = Button(label="下一頁", style=discord.ButtonStyle.secondary, disabled=self.current_page == self.total_pages - 1)
        next_button.callback = self.next_page
        self.add_item(next_button)
        self.add_item(AllParticipantsButton())

    async def prev_page(self, interaction: discord.Interaction):
        self.current_page -= 1
        self.update_buttons()
        logging.debug(f"切換到上一頁: 當前頁 {self.current_page}")
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    async def next_page(self, interaction: discord.Interaction):
        self.current_page += 1
        self.update_buttons()
        logging.debug(f"切換到下一頁: 當前頁 {self.current_page}")
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    def get_embed(self):
        embed = discord.Embed(
            title="🎁 焰獄拍賣會獎品清單",
            description="請點擊下方按鈕參加你想要的獎品抽獎，或查看所有參加者清單：",
            color=discord.Color.red()  # 紅色邊框
        )
        if not self.prize_dict:
            embed.add_field(
                name="📭 無獎品",
                value="目前沒有獎品，請使用 !add_prize 新增。",
                inline=False
            )
        else:
            start_idx = self.current_page * self.page_size
            end_idx = min(start_idx + self.page_size, len(self.prize_dict))
            try:
                prize_items = [item for item in self.prize_dict.items()][start_idx:end_idx]
                logging.debug(f"get_embed: 顯示獎品索引 {start_idx} 到 {end_idx}, 項目: {[name for name, _ in prize_items]}")
                for prize, info in prize_items:
                    embed.add_field(
                        name=f"📦 {prize}",
                        value=f"**得獎人數**：{info['winners']}\n**參加者**：{len(info['participants'])} 人",
                        inline=True
                    )
            except Exception as e:
                logging.error(f"生成嵌入欄位失敗: {e}, prize_dict 類型: {type(self.prize_dict)}")
                embed.add_field(
                    name="❌ 錯誤",
                    value="無法顯示獎品清單，請聯繫管理員。",
                    inline=False
                )
        embed.set_footer(text=f"頁數：{self.current_page + 1}/{self.total_pages} | 請遵守抽獎規則！")
        return embed
    

class PrizeJoinView(View):
    def __init__(self, prize_dict):
        super().__init__(timeout=None)
        for prize in prize_dict:
            self.add_item(PrizeJoinButton(prize))
        self.add_item(AllParticipantsButton())

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
async def show_prizes(ctx):
    global prizes_data
    try:
        content = [k for k in prizes_data.keys()][:5] if isinstance(prizes_data, dict) else prizes_data
        logging.debug(f"執行 !show_prizes, prizes_data 類型: {type(prizes_data)}, 內容: {content}")
    except Exception as e:
        logging.error(f"記錄 prizes_data 失敗: {e}")
    if not isinstance(prizes_data, dict):
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
    view = PaginationView(prizes_data)
    await ctx.send(embed=view.get_embed(), view=view)

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

@bot.command()
@commands.has_permissions(administrator=True)
async def list(ctx, *, prize_names):
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
    
    # 嚴格檢查 prizes_data
    print(f"DEBUG: prizes_data 類型: {type(prizes_data)}")
    print(f"DEBUG: prizes_data 內容: {prizes_data}")
    
    if not isinstance(prizes_data, dict):
        await ctx.send("❌ 獎品資料異常，請重新啟動 Bot")
        return
    
    if not prizes_data:
        await ctx.send("📭 目前沒有獎品。")
        return

    msg = []
    
    # 安全地獲取獎品名稱列表
    prize_names = []
    for key in prizes_data:
        if isinstance(key, str):
            prize_names.append(key)
    
    print(f"DEBUG: 安全獲取的獎品名稱: {prize_names}")
    
    for name in prize_names[:]:  # 使用切片創建副本
        print(f"DEBUG: 處理獎品: {name}")
        
        if name not in prizes_data:
            print(f"DEBUG: 獎品 {name} 已不存在，跳過")
            continue
        
        info = prizes_data[name]
        participants = info.get("participants", [])
        winner_count = info.get("winners", 1)
        
        print(f"DEBUG: 獎品 {name} - 參加者: {len(participants)}, 得主數: {winner_count}")
        
        if not participants:
            msg.append(f"😢 「{name}」沒有人參加，無法抽獎。")
        else:
            actual_winners = min(winner_count, len(participants))
            try:
                winners = random.sample(participants, actual_winners)
                print(f"DEBUG: 抽中: {winners}")
                
                # 建立 @mention 列表
                mention_list = []
                
                for participant_id in winners:
                    print(f"DEBUG: 處理參加者: {participant_id} (類型: {type(participant_id)})")
                    
                    user = None
                    try:
                        # 嘗試轉換為整數 ID
                        user_id = int(participant_id)
                        print(f"DEBUG: 解析為 ID: {user_id}")
                        
                        # 先嘗試 get_member
                        user = ctx.guild.get_member(user_id)
                        if not user:
                            # 再嘗試 fetch_member
                            print(f"DEBUG: get_member 失敗，嘗試 fetch_member")
                            try:
                                user = await ctx.guild.fetch_member(user_id)
                                print(f"DEBUG: fetch_member 成功")
                            except Exception as e:
                                print(f"DEBUG: fetch_member 失敗: {e}")
                        
                        if user:
                            print(f"DEBUG: 成功找到用戶: {user.display_name} (ID: {user.id})")
                            mention_list.append(user.mention)
                        else:
                            print(f"DEBUG: 找不到用戶 ID {user_id}")
                            # 嘗試根據名稱查找
                            for member in ctx.guild.members:
                                if str(member.id) == participant_id:
                                    user = member
                                    mention_list.append(user.mention)
                                    print(f"DEBUG: 通過成員列表找到: {user.display_name}")
                                    break
                            else:
                                mention_list.append(f"**ID:{participant_id}**")
                                
                    except ValueError:
                        print(f"DEBUG: 非數字 ID，視為舊資料: {participant_id}")
                        # 舊資料格式，嘗試名稱匹配
                        for member in ctx.guild.members:
                            if (member.display_name == participant_id or 
                                member.name == participant_id):
                                user = member
                                mention_list.append(user.mention)
                                print(f"DEBUG: 名稱匹配成功: {user.display_name}")
                                break
                        else:
                            mention_list.append(f"**@{participant_id}**")
                
                # 建立得獎訊息
                if len(winners) == 1:
                    winner_mentions = mention_list[0]
                else:
                    winner_mentions = "、".join(mention_list[:-1]) + f" 和 {mention_list[-1]}"
                
                msg.append(f"🎉 恭喜 {winner_mentions} 獲得「{name}」！")
                
            except ValueError as e:
                print(f"DEBUG: 抽獎錯誤: {e}")
                msg.append(f"😢 「{name}」參加者不足以抽出 {winner_count} 名得主。")
        
        # 刪除獎品
        if name in prizes_data:
            del prizes_data[name]
            print(f"DEBUG: 已刪除獎品 {name}")
    
    # 發送結果
    if msg:
        await ctx.send("\n".join(msg))
    else:
        await ctx.send("沒有可處理的獎品。")
    
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
        print(f"DEBUG: Welcome channel (ID: {CHANNEL_ID}) not found")


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
    if not isinstance(prizes_data, dict):
        await ctx.send("❌ 獎品資料異常，無法備份。")
        return
    try:
        # 讀取檔案
        with open('prizes_data.json', 'r', encoding='utf-8') as f:
            file_content = f.read()
        
        # 將內容編碼為 base64（避免 Discord 檔案上傳限制，如果內容過長）
        encoded_content = base64.b64encode(file_content.encode('utf-8')).decode('utf-8')
        
        # 發送為檔案附件（如果內容小）或文字（編碼後）
        if len(file_content) < 8000:  # Discord 訊息限制
            await ctx.send(f"✅ 備份內容（Base64 編碼）：\n```{encoded_content}```\n解碼後可還原為 JSON。")
        else:
            # 上傳為檔案
            with open('prizes_data_backup.json', 'w', encoding='utf-8') as f:
                f.write(file_content)
            with open('prizes_data_backup.json', 'rb') as f:
                await ctx.send("✅ 備份檔案：", file=discord.File(f, 'prizes_data_backup.json'))
            os.remove('prizes_data_backup.json')  # 刪除臨時檔案
        
        logging.debug(f"備份執行成功，用戶: {ctx.author.id}")
    except FileNotFoundError:
        await ctx.send("❌ 找不到 prizes_data.json 檔案。")
    except Exception as e:
        await ctx.send(f"❌ 備份失敗：{e}")
        logging.error(f"備份錯誤: {e}")

@bot.command()
@commands.has_permissions(administrator=True)
async def restore(ctx, *, json_content=None):
    global prizes_data
    if not json_content:
        await ctx.send("❌ 請提供 JSON 內容（例如貼上檔案內容）。")
        return
    try:
        prizes_data = json.loads(json_content)
        save_prizes()
        await ctx.send("✅ 還原成功！")
    except Exception as e:
        await ctx.send(f"❌ 還原失敗：{e}")        

keep_alive.keep_alive()
bot.run(TOKEN)