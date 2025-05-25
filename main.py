from fastapi import FastAPI, Request, Form, Depends, HTTPException, status, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy import create_engine, Column, Integer, String, DateTime, JSON, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from datetime import datetime
import json
import os
import qrcode
from io import BytesIO
import base64
import secrets
import shutil
from typing import Optional, List, Dict, Tuple, Any
from fastapi import WebSocket
from fastapi import WebSocketDisconnect
from fastapi import BackgroundTasks
import datetime as dt # Import datetime as dt to avoid conflict if datetime was used as variable name
from pydantic import BaseModel

# FastAPI 앱 생성
app = FastAPI()

# 응답 모델 정의
class OnlineTableInfo(BaseModel):
    table_id: int
    nickname: str

class OnlineTablesResponse(BaseModel):
    online_tables: List[OnlineTableInfo]

class GiftOrderRequest(BaseModel):
    from_table_id: int
    to_table_id: int
    menu: Dict[str, int]  # item_id: quantity
    message: Optional[str] = None

# KST timezone object
KST = dt.timezone(dt.timedelta(hours=9))

# Custom Jinja2 filter to convert UTC to KST and format
def to_kst_filter(utc_dt):
    if not utc_dt: # Handle None or empty values
        return ""
    if isinstance(utc_dt, str): # If it's already a string, try to parse, or return as is
        try:
            # Attempt to parse if it's a common ISO format string
            # This might need adjustment based on how strings are stored/passed
            utc_dt = dt.datetime.fromisoformat(utc_dt.replace('Z', '+00:00'))
        except ValueError:
            return utc_dt # Return original string if parsing fails
    
    if utc_dt.tzinfo is None:
        utc_dt = utc_dt.replace(tzinfo=dt.timezone.utc) # Assume naive datetime is UTC
    
    kst_dt = utc_dt.astimezone(KST)
    return kst_dt.strftime("%Y-%m-%d %H:%M") # Desired KST format

# 정적 파일과 템플릿 설정
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# 커스텀 Jinja2 필터 추가
def format_currency(value):
    """숫자를 통화 형식으로 포맷팅 (예: 1,234,567)"""
    return "{:,}".format(int(value))

templates.env.filters["format_currency"] = format_currency
templates.env.filters["kst"] = to_kst_filter # Register the new KST filter

# 관리자 인증 설정
security = HTTPBasic()
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "your-secure-password")

def verify_admin(credentials: HTTPBasicCredentials = Depends(security)):
    correct_username = secrets.compare_digest(credentials.username, ADMIN_USERNAME)
    correct_password = secrets.compare_digest(credentials.password, ADMIN_PASSWORD)
    
    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

# QR 코드 저장 디렉토리 생성
QR_DIR = "static/qr"
os.makedirs(QR_DIR, exist_ok=True)

# 업로드 디렉토리 생성
UPLOAD_DIR = "static/uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# 데이터베이스 설정
SQLALCHEMY_DATABASE_URL = "sqlite:///./orders.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Order 모델 정의
class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    table_id = Column(Integer)
    menu = Column(JSON)
    amount = Column(Integer)
    payment_status = Column(String)  # 'pending' or 'confirmed'
    cooking_status = Column(String, default="pending")  # 'pending', 'cooking', 'completed'
    created_at = Column(DateTime, default=datetime.utcnow)
    confirmed_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    table_id = Column(Integer, index=True)  # 보내는 사람의 테이블 번호
    message = Column(String)
    nickname = Column(String, default="손님")  # 닉네임
    is_global = Column(Boolean, default=True)  # True: 전체 채팅, False: 개별 채팅
    target_table_id = Column(Integer, nullable=True)  # 개별 채팅 시 대상 테이블 (향후 확장용)
    created_at = Column(DateTime, default=datetime.utcnow)

class MenuItem(Base):
    __tablename__ = "menu_items"

    id = Column(Integer, primary_key=True, index=True)
    name_kr = Column(String, unique=True, index=True)  # 한글 이름
    name_en = Column(String, unique=True, index=True)  # 영문 이름 (코드용)
    price = Column(Integer)
    category = Column(String)  # 'drinks', 'main_dishes', 'side_dishes'
    description = Column(String, nullable=True)  # 메뉴 설명
    image_filename = Column(String, nullable=True)  # 이미지 파일명
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

# 데이터베이스 테이블 생성
Base.metadata.create_all(bind=engine)

# 의존성
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# 초기 메뉴 데이터 생성 함수
def init_menu_data(db: Session):
    """초기 메뉴 데이터 생성"""
    if db.query(MenuItem).first() is None:
        initial_menu = [
            MenuItem(name_kr="상차림비(인당)", name_en="table", price=6000, category="table", image_filename="table.png"), # Typically no specific image
            MenuItem(
                name_kr="🌟 두근두근 2인 세트",
                name_en="🌟 2-person set",
                price=32000,
                category="set_menu",
                description="둘이 앉아 조용히 속닥속닥 🌿\n(숲속 삼겹살 2인분 + 두부김치 + 음료 2잔 + 랜덤 뽑기권 1개)",
                image_filename="2-person-set.png"
            ),
            MenuItem(
                name_kr="🌟 단짝 4인 세트",
                name_en="🌟 4-person set",
                price=51900,
                category="set_menu",
                description="친구들, 이웃들 다 모여~ 파티 파티 🎇\n(숲속 삼겹살 3인분 + 두부김치 + 김치볶음밥 + 음료 4잔 + 랜덤 뽑기권 2개)",
                image_filename="4-person-set.png"
            ),
            MenuItem(
                name_kr="🌟 모여봐요 6인 세트",
                name_en="🌟 6-person set",
                price=77900,
                category="set_menu",
                description="마을 축제처럼 신나게!\n(숲속 삼겹살 5인분 + 두부김치 + 김치볶음밥 + 콘치즈 + 마을 장터 나초 + 음료 6잔 + 랜덤 뽑기권 4개)",
                image_filename="6-person-set.png"
            ),
            MenuItem(
                name_kr="숲속 삼겹살",
                name_en="samgyeopsal",
                price=8900,
                category="main_dishes",
                description="바람 솔솔~ 숲속 바비큐 파티 시작!\n지글지글 구워서 따끈하게 한 점 🐷🔥",
                image_filename="samgyeopsal.png"
            ),
            MenuItem(
                name_kr="너굴의 비밀 레시비 김볶밥",
                name_en="kimchi_fried_rice",
                price=7900,
                category="main_dishes",
                description="너굴 마트표 김치로 만든 마법의 볶음밥!\n밤하늘 아래서 먹으면 꿀맛 🍚🌟",
                image_filename="kimchi_fried_rice.png"
            ),
            MenuItem(
                name_kr="셰프 프랭클린의 두부김치",
                name_en="tofu_kimchi",
                price=11900,
                category="main_dishes",
                description="마을 최고 셰프의 두부 + 정성으로 구운 김치\n포근하고 든든한 마을 스타일 안주 💬🍽️",
                image_filename="tofu_kimchi.png"
            ),
            MenuItem(
                name_kr="둘기가 숨어먹는 콘치즈",
                name_en="corn_cheese",
                price=6900,
                category="main_dishes",
                description="비둘기 마스터의 최애 간식!\n달콤하고 고소해서 숟가락이 멈추지 않아요 🌽🧀✨",
                image_filename="corn_cheese.png"
            ),
            MenuItem(
                name_kr="마을 장터 나초",
                name_en="nachos",
                price=6900,
                category="main_dishes",
                description="마을 주민들이 손수 만든 바삭바삭 나초 🌿\n모닥불 옆에서 친구들과 나눠 먹는 소중한 맛 🎇",
                image_filename="nachos.png"
            ),
            MenuItem(
                name_kr="숲속 바람 사이다",
                name_en="forest_cider",
                price=1900,
                category="drinks",
                description="시원한 바람처럼 톡톡~ 상쾌하게 🌬️🥤\n(청량감 최고! 더위도 걱정 없어요 ❄️)",
                image_filename="forest_cider.png"
            ),
            MenuItem(
                name_kr="너굴 장터 콜라",
                name_en="raccoon_cola",
                price=1900,
                category="drinks",
                description="마을 장터에서 제일 인기 많은 탄산음료!\n톡 쏘는 맛에 기분도 두 배 🎉🐾",
                image_filename="raccoon_cola.png"
            ),
            MenuItem(
                name_kr="부엉의 에너지 드링크",
                name_en="owl_energy_drink",
                price=1900,
                category="drinks",
                description="밤새 파티? 문제없어! 🦉🌙\n부엉이처럼 깨어있게 도와주는 마법의 한 캔 🪄🥤",
                image_filename="owl_energy_drink.png"
            ),
        ]
        db.add_all(initial_menu)
        db.commit()

# 메뉴 데이터 초기화
init_menu_data(next(get_db()))

# 메뉴 관련 함수들 (리팩토링된 버전)
def get_menu_data(db: Session) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, str], Dict[str, List[MenuItem]], Dict[str, str]]:
    """활성화된 메뉴 데이터를 다양한 형식으로 반환합니다."""
    active_items = db.query(MenuItem).filter(MenuItem.is_active == True).order_by(MenuItem.id).all()

    # order.js 에 전달될 메뉴 아이템 정보 (ID를 키로, 아이템 상세 정보를 값으로 하는 딕셔너리)
    menu_item_details_for_js = {
        str(item.id): {
            "id": str(item.id),
            "name_kr": item.name_kr,
            "price": item.price,
            "is_active": item.is_active
        } for item in active_items
    }
    menu_names_by_id = {str(item.id): item.name_kr for item in active_items}

    # order.html 및 카테고리 기반 뷰를 위한 구조
    # 카테고리 순서 정의 (order.html 표시 순서)
    category_order = ["table", "set_menu", "main_dishes", "drinks", "side_dishes"]
    
    menu_items_grouped_by_category = {category: [] for category in category_order}
    for item in active_items:
        if item.category in menu_items_grouped_by_category:
            menu_items_grouped_by_category[item.category].append(item)

    # 세트메뉴는 2인 -> 4인 -> 6인 순서로 정렬
    if menu_items_grouped_by_category["set_menu"]:
        menu_items_grouped_by_category["set_menu"].sort(key=lambda x: (
            0 if "2인" in x.name_kr else
            1 if "4인" in x.name_kr else
            2 if "6인" in x.name_kr else
            3
        ))

    # 빈 카테고리 키는 유지하되, 리스트가 비어있음을 order.html에서 처리

    category_display_names = {
        "table": "상차림비",
        "set_menu": "세트 메뉴",
        "main_dishes": "메인 요리",
        "drinks": "음료",
        "side_dishes": "사이드 메뉴"
    }
    
    return menu_item_details_for_js, menu_names_by_id, menu_items_grouped_by_category, category_display_names

def generate_qr_code(url: str, table_id: int) -> str:
    """QR 코드를 생성하고 저장된 경로를 반환합니다."""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(url)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")
    filename = f"table_{table_id}.png"
    filepath = os.path.join(QR_DIR, filename)
    img.save(filepath)
    
    return filepath

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

# 채팅 페이지(구현 예정정)
@app.get("/chat", response_class=HTMLResponse)
async def chat(request: Request):
    return templates.TemplateResponse("chat.html", {"request": request})

@app.post("/chat/send")
async def send_chat_message(
    request: Request,
    table_id: int = Form(...),
    message: str = Form(...),
    nickname: str = Form(None),
    target_table_id: int = Form(None),  # 개인 메시지 대상 테이블 ID
    db: Session = Depends(get_db)
):
    """채팅 메시지 전송 (전체 채팅 또는 개인 메시지)"""
    try:
        # 닉네임 설정 (없으면 기본값)
        if nickname:
            manager.set_nickname(table_id, nickname)
            display_nickname = nickname
        else:
            display_nickname = manager.get_nickname(table_id)
        
        # 개인 메시지인지 전체 메시지인지 판단
        is_private = target_table_id is not None
        
        # 메시지를 데이터베이스에 저장
        chat_message = ChatMessage(
            table_id=table_id,
            message=message,
            nickname=display_nickname,
            is_global=not is_private,  # 개인 메시지면 False, 전체 메시지면 True
            target_table_id=target_table_id if is_private else None
        )
        db.add(chat_message)
        db.commit()
        db.refresh(chat_message)
        
        # WebSocket으로 실시간 전송
        message_data = {
            "type": "chat_message",
            "id": chat_message.id,
            "table_id": table_id,
            "nickname": display_nickname,
            "message": message,
            "created_at": chat_message.created_at.isoformat(),
            "formatted_time": to_kst_filter(chat_message.created_at),
            "is_private": is_private,
            "target_table_id": target_table_id
        }
        
        if is_private:
            # 개인 메시지인 경우 보낸 사람과 받는 사람에게만 전송
            await manager.broadcast_to_table(table_id, json.dumps(message_data))  # 보낸 사람
            await manager.broadcast_to_table(target_table_id, json.dumps(message_data))  # 받는 사람
        else:
            # 전체 메시지인 경우 모든 사람에게 전송
            await manager.broadcast_to_all(json.dumps(message_data))
        
        return {"success": True, "message_id": chat_message.id, "is_private": is_private}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/chat/messages")
async def get_chat_messages(
    table_id: int = None,  # 현재 사용자의 테이블 ID 추가
    limit: int = 50,
    before_id: int = None,
    db: Session = Depends(get_db)
):
    """채팅 메시지 목록 조회 (전체 메시지 + 관련된 개인 메시지)"""
    
    if table_id:
        # 전체 메시지 + 해당 테이블과 관련된 개인 메시지
        query = db.query(ChatMessage).filter(
            (ChatMessage.is_global == True) |  # 전체 메시지
            (ChatMessage.table_id == table_id) |  # 내가 보낸 개인 메시지
            (ChatMessage.target_table_id == table_id)  # 나에게 온 개인 메시지
        )
    else:
        # table_id가 없으면 전체 메시지만
        query = db.query(ChatMessage).filter(ChatMessage.is_global == True)
    
    if before_id:
        query = query.filter(ChatMessage.id < before_id)
    
    messages = query.order_by(ChatMessage.created_at.desc()).limit(limit).all()
    
    return {
        "messages": [
            {
                "id": msg.id,
                "table_id": msg.table_id,
                "nickname": msg.nickname,
                "message": msg.message,
                "created_at": msg.created_at.isoformat(),
                "formatted_time": to_kst_filter(msg.created_at),
                "is_private": not msg.is_global,
                "target_table_id": msg.target_table_id
            }
            for msg in reversed(messages)
        ]
    }

@app.get("/chat/online-tables", response_model=OnlineTablesResponse)
async def get_online_tables():
    """현재 온라인인 테이블 목록 조회"""
    try:
        online_tables = manager.get_online_tables()
        table_info = []
        for table_id in online_tables:
            try:
                nickname = manager.get_nickname(table_id)
                # nickname이 None이거나 빈 문자열인 경우 기본값 사용
                if not nickname:
                    nickname = f"테이블{table_id}"
                
                table_info.append(OnlineTableInfo(
                    table_id=table_id,
                    nickname=str(nickname)  # 문자열로 확실히 변환
                ))
            except Exception as e:
                print(f"Error processing table {table_id}: {str(e)}")
                # 개별 테이블 처리 오류 시 기본값으로 추가
                table_info.append(OnlineTableInfo(
                    table_id=table_id,
                    nickname=f"테이블{table_id}"
                ))
        
        return OnlineTablesResponse(online_tables=table_info)
    except Exception as e:
        print(f"Error in get_online_tables: {str(e)}")
        # 오류 발생 시 빈 목록 반환
        return OnlineTablesResponse(online_tables=[])

@app.get("/chat/{table_id}", response_class=HTMLResponse)
async def chat_with_table(request: Request, table_id: int, db: Session = Depends(get_db)):
    """특정 테이블 번호로 채팅 페이지 접속"""
    # 최근 채팅 메시지 조회 (최근 50개)
    recent_messages = db.query(ChatMessage).filter(
        ChatMessage.is_global == True
    ).order_by(ChatMessage.created_at.desc()).limit(50).all()
    recent_messages.reverse()  # 시간 순으로 정렬
    
    # 현재 온라인인 테이블 목록
    online_tables = manager.get_online_tables()
    
    return templates.TemplateResponse("chat.html", {
        "request": request,
        "table_id": table_id,
        "recent_messages": recent_messages,
        "online_tables": online_tables
    })

@app.get("/generate-qr/{table_id}")
async def generate_table_qr(table_id: int, request: Request):
    """특정 테이블의 QR 코드를 생성하고 다운로드합니다."""
    base_url = request.base_url
    order_url = f"{base_url}order?table={table_id}"
    qr_path = generate_qr_code(order_url, table_id)
    
    return FileResponse(
        qr_path,
        media_type="image/png",
        filename=f"table_{table_id}_qr.png"
    )

@app.get("/generate-all-qr")
async def generate_all_qr(request: Request):
    """모든 테이블의 QR 코드를 생성하고 ZIP 파일로 다운로드합니다."""
    import zipfile
    import tempfile
    import os
    
    # 임시 디렉토리 생성
    temp_dir = tempfile.mkdtemp()
    try:
        # 임시 ZIP 파일 생성
        zip_path = os.path.join(temp_dir, "table_qr_codes.zip")
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            base_url = request.base_url
            for table_id in range(1, 51):
                order_url = f"{base_url}order?table={table_id}"
                qr_path = generate_qr_code(order_url, table_id)
                # ZIP 파일에 추가할 때 파일 이름만 사용
                zip_file.write(qr_path, f"table_{table_id}_qr.png")
        
        # FileResponse 생성 시 임시 디렉토리 경로를 background_tasks에 추가
        response = FileResponse(
            zip_path,
            media_type="application/zip",
            filename="table_qr_codes.zip",
            background=BackgroundTasks()
        )
        
        # 응답이 완료된 후 임시 디렉토리 삭제
        response.background.add_task(shutil.rmtree, temp_dir)
        
        return response
    except Exception as e:
        # 오류 발생 시 임시 디렉토리 삭제
        shutil.rmtree(temp_dir)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/order", response_class=HTMLResponse)
async def order_page(request: Request, table: int, db: Session = Depends(get_db)):
    menu_item_details_for_js, menu_names_by_id, menu_items_grouped_by_category, category_display_names = get_menu_data(db)
    
    return templates.TemplateResponse(
        "order.html",
        {
            "request": request, 
            "table_id": table, 
            "menu_items_by_category": menu_items_grouped_by_category,
            "category_display_names": category_display_names,
            "menu_item_details_for_js": menu_item_details_for_js
        }
    )

@app.post("/submit_order")
async def submit_order(
    request: Request,
    table_id: int = Form(...),
    menu: str = Form(...),
    db: Session = Depends(get_db)
):
    try:
        print(f"Received order request - table_id: {table_id}, menu: {menu}")
        
        # 1. 메뉴 데이터 가져오기
        try:
            menu_item_details_for_js, menu_names_by_id, menu_items_grouped_by_category, category_display_names = get_menu_data(db)
            print(f"Retrieved menu data - items: {menu_item_details_for_js}, names: {menu_names_by_id}")
        except Exception as e:
            print(f"Error getting menu data: {str(e)}")
            raise HTTPException(status_code=500, detail="Failed to retrieve menu data")
        
        # 2. 주문 메뉴 파싱 및 유효성 검사
        try:
            order_menu = json.loads(menu)
            if not isinstance(order_menu, dict):
                raise ValueError("Menu data must be a dictionary")
            print(f"Parsed order menu: {order_menu}")
        except json.JSONDecodeError as e:
            print(f"Invalid JSON format: {str(e)}")
            raise HTTPException(status_code=400, detail="Invalid menu data format")
        except ValueError as e:
            print(f"Invalid menu data structure: {str(e)}")
            raise HTTPException(status_code=400, detail=str(e))
        
        # 3. 주문 금액 계산 및 메뉴 유효성 검사
        total_amount = 0
        valid_order_items = {}
        
        for item_id, quantity in order_menu.items():
            try:
                quantity = int(quantity)
                if quantity <= 0:
                    print(f"Warning: Invalid quantity {quantity} for item {item_id}")
                    continue
                    
                # item_id를 문자열로 변환하여 메뉴 아이템 조회
                item = menu_item_details_for_js.get(str(item_id))
                if not item:
                    print(f"Warning: Menu item not found for ID {item_id}")
                    continue
                    
                if not item['is_active']:
                    print(f"Warning: Menu item {item_id} is not active")
                    continue
                
                item_total = item['price'] * quantity
                total_amount += item_total
                valid_order_items[item_id] = quantity
                print(f"Added item {item_id}: {quantity} x {item['price']} = {item_total}")
                
            except (ValueError, TypeError) as e:
                print(f"Error processing item {item_id}: {str(e)}")
                continue
        
        if not valid_order_items:
            raise HTTPException(status_code=400, detail="No valid items in order")
        
        print(f"Final order items: {valid_order_items}")
        print(f"Calculated total amount: {total_amount}")
        
        # 4. 주문 생성
        try:
            order = Order(
                table_id=table_id,
                menu=valid_order_items,
                amount=total_amount,
                payment_status="pending"
            )
            db.add(order)
            db.commit()
            db.refresh(order)
            print(f"Created order with ID: {order.id}")
        except Exception as e:
            print(f"Database error: {str(e)}")
            db.rollback()
            raise HTTPException(status_code=500, detail="Failed to create order")
        
        # 5. WebSocket 알림 (실패해도 주문은 성공)
        try:
            await manager.broadcast(json.dumps({
                "type": "new_order",
                "order_id": order.id,
                "table_id": table_id,
                "amount": total_amount
            }))
            print("WebSocket notification sent")
        except Exception as ws_error:
            print(f"WebSocket error (non-critical): {str(ws_error)}")
        
        # 6. 주문 성공 페이지 반환
        return templates.TemplateResponse(
            "order_success.html",
            {
                "request": request,
                "order": order,
                "table_id": table_id,
                "menu_names": menu_names_by_id
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Unexpected error in submit_order: {str(e)}")
        print(f"Error type: {type(e)}")
        import traceback
        print(f"Traceback: {traceback.format_exc()}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/admin/orders", response_class=HTMLResponse)
async def admin_orders(
    request: Request,
    db: Session = Depends(get_db),
    username: str = Depends(verify_admin)
):
    # 메뉴 데이터 가져오기
    menu_item_details_for_js, menu_names_by_id, menu_items_grouped_by_category, category_display_names = get_menu_data(db)
    
    # 결제 대기 중인 주문
    pending_orders = db.query(Order).filter(Order.payment_status == "pending").all()
    
    # 조리 중인 주문
    cooking_orders = db.query(Order).filter(
        Order.payment_status == "confirmed",
        Order.cooking_status.in_(["pending", "cooking"])
    ).order_by(Order.confirmed_at.desc()).all()
    
    # 완료된 주문
    completed_orders = db.query(Order).filter(
        Order.payment_status == "confirmed",
        Order.cooking_status == "completed"
    ).order_by(Order.completed_at.desc()).limit(10).all()
    
    return templates.TemplateResponse(
        "admin_orders.html",
        {
            "request": request,
            "pending_orders": pending_orders,
            "cooking_orders": cooking_orders,
            "completed_orders": completed_orders,
            "username": username,
            "menu_names": menu_names_by_id
        }
    )

@app.post("/admin/orders/confirm/{order_id}")
async def confirm_order(
    order_id: int,
    db: Session = Depends(get_db),
    username: str = Depends(verify_admin)
):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    order.payment_status = "confirmed"
    order.confirmed_at = datetime.utcnow()
    db.commit()
    
    return RedirectResponse(url="/admin/orders", status_code=303)

@app.get("/kitchen", response_class=HTMLResponse)
async def kitchen_display(
    request: Request,
    db: Session = Depends(get_db),
    username: str = Depends(verify_admin)
):
    # 메뉴 데이터 가져오기
    menu_item_details_for_js, menu_names_by_id, menu_items_grouped_by_category, category_display_names = get_menu_data(db)
    
    # 조리 중인 주문 (결제 확인된 주문)
    cooking_orders = db.query(Order).filter(
        Order.payment_status == "confirmed",
        Order.cooking_status.in_(["pending", "cooking"])
    ).order_by(Order.confirmed_at.desc()).all()
    
    # 결제 대기 중인 주문
    pending_orders = db.query(Order).filter(
        Order.payment_status == "pending"
    ).order_by(Order.created_at.desc()).all()
    
    # 완료된 주문
    completed_orders = db.query(Order).filter(
        Order.payment_status == "confirmed",
        Order.cooking_status == "completed"
    ).order_by(Order.completed_at.desc()).limit(10).all()
    
    return templates.TemplateResponse(
        "kitchen.html",
        {
            "request": request,
            "cooking_orders": cooking_orders,
            "pending_orders": pending_orders,
            "completed_orders": completed_orders,
            "username": username,
            "menu_names": menu_names_by_id
        }
    )

@app.post("/kitchen/update-status/{order_id}")
async def update_cooking_status(
    order_id: int,
    status: str = Form(...),
    db: Session = Depends(get_db),
    username: str = Depends(verify_admin)
):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    order.cooking_status = status
    if status == "completed":
        order.completed_at = datetime.utcnow()
    
    db.commit()
    return RedirectResponse(url="/kitchen", status_code=303)

@app.get("/admin/logout")
async def logout():
    """로그아웃 처리"""
    response = RedirectResponse(url="/", status_code=303)
    response.headers["WWW-Authenticate"] = "Basic"
    return response

@app.get("/admin/table/{table_id}", response_class=HTMLResponse)
async def table_order_history(
    request: Request,
    table_id: int,
    status: str = None,
    limit: int = 10,
    db: Session = Depends(get_db),
    username: str = Depends(verify_admin)
):
    """테이블별 주문 내역 조회"""
    # 메뉴 데이터 가져오기
    menu_item_details_for_js, menu_names_by_id, menu_items_grouped_by_category, category_display_names = get_menu_data(db)
    
    query = db.query(Order).filter(Order.table_id == table_id)
    
    # 상태별 필터링
    if status == "cooking":
        query = query.filter(
            Order.payment_status == "confirmed",
            Order.cooking_status.in_(["pending", "cooking"])
        )
    elif status == "completed":
        query = query.filter(
            Order.payment_status == "confirmed",
            Order.cooking_status == "completed"
        )
    elif status == "pending":
        query = query.filter(Order.payment_status == "pending")
    
    # 전체 주문 수 조회
    total_orders = query.count()
    
    # 최근 주문 조회
    orders = query.order_by(Order.created_at.desc()).limit(limit).all()
    
    return templates.TemplateResponse(
        "table_history.html",
        {
            "request": request,
            "table_id": table_id,
            "orders": orders,
            "total_orders": total_orders,
            "current_status": status,
            "current_limit": limit,
            "username": username,
            "menu_names": menu_names_by_id  # 메뉴 이름 정보 추가
        }
    )

@app.get("/admin/menu", response_class=HTMLResponse)
async def menu_management(
    request: Request,
    db: Session = Depends(get_db),
    username: str = Depends(verify_admin)
):
    """메뉴 관리 페이지"""
    menu_items = db.query(MenuItem).order_by(MenuItem.category, MenuItem.name_kr).all()
    return templates.TemplateResponse(
        "menu_management.html",
        {
            "request": request,
            "menu_items": menu_items,
            "username": username
        }
    )

@app.post("/admin/menu/add")
async def add_menu_item(
    request: Request,
    name_kr: str = Form(...),
    name_en: str = Form(...),
    price: int = Form(...),
    category: str = Form(...),
    description: str = Form(None),
    image: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    username: str = Depends(verify_admin)
):
    """새 메뉴 추가"""
    try:
        # 이미지 파일 처리
        image_filename = None
        if image:
            # 파일 확장자 검사
            if not image.content_type.startswith('image/'):
                raise HTTPException(status_code=400, detail="이미지 파일만 업로드 가능합니다.")
            
            # 파일명 생성 (timestamp + original filename)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            image_filename = f"{timestamp}_{image.filename}"
            file_path = os.path.join(UPLOAD_DIR, image_filename)
            
            # 파일 저장
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(image.file, buffer)

        menu_item = MenuItem(
            name_kr=name_kr,
            name_en=name_en,
            price=price,
            category=category,
            description=description,
            image_filename=image_filename
        )
        db.add(menu_item)
        db.commit()
        return RedirectResponse(url="/admin/menu", status_code=303)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/admin/menu/update/{item_id}")
async def update_menu_item(
    item_id: int,
    name_kr: str = Form(...),
    name_en: str = Form(...),
    price: int = Form(...),
    category: str = Form(...),
    description: str = Form(None),
    is_active: bool = Form(False),
    image: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    username: str = Depends(verify_admin)
):
    """메뉴 수정"""
    menu_item = db.query(MenuItem).filter(MenuItem.id == item_id).first()
    if not menu_item:
        raise HTTPException(status_code=404, detail="Menu item not found")
    
    try:
        # 이미지 파일 처리
        if image:
            # 파일 확장자 검사
            if not image.content_type.startswith('image/'):
                raise HTTPException(status_code=400, detail="이미지 파일만 업로드 가능합니다.")
            
            # 기존 이미지 삭제
            if menu_item.image_filename:
                old_file_path = os.path.join(UPLOAD_DIR, menu_item.image_filename)
                if os.path.exists(old_file_path):
                    os.remove(old_file_path)
            
            # 새 이미지 저장
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            image_filename = f"{timestamp}_{image.filename}"
            file_path = os.path.join(UPLOAD_DIR, image_filename)
            
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(image.file, buffer)
            
            menu_item.image_filename = image_filename

        menu_item.name_kr = name_kr
        menu_item.name_en = name_en
        menu_item.price = price
        menu_item.category = category
        menu_item.description = description
        menu_item.is_active = is_active
        db.commit()
        return RedirectResponse(url="/admin/menu", status_code=303)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/admin/menu/delete/{item_id}")
async def delete_menu_item(
    item_id: int,
    db: Session = Depends(get_db),
    username: str = Depends(verify_admin)
):
    """메뉴 삭제 (비활성화)"""
    menu_item = db.query(MenuItem).filter(MenuItem.id == item_id).first()
    if not menu_item:
        raise HTTPException(status_code=404, detail="Menu item not found")
    
    # 이미지 파일 삭제
    if menu_item.image_filename:
        file_path = os.path.join(UPLOAD_DIR, menu_item.image_filename)
        if os.path.exists(file_path):
            os.remove(file_path)
    
    menu_item.is_active = False
    db.commit()
    return RedirectResponse(url="/admin/menu", status_code=303)

# WebSocket 연결 관리를 위한 클래스
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[int, List[WebSocket]] = {}  # table_id: [websockets]
        self.table_nicknames: Dict[int, str] = {}  # table_id: nickname

    async def connect(self, websocket: WebSocket, table_id: int):
        await websocket.accept()
        if table_id not in self.active_connections:
            self.active_connections[table_id] = []
        self.active_connections[table_id].append(websocket)

    def disconnect(self, websocket: WebSocket, table_id: int):
        if table_id in self.active_connections:
            self.active_connections[table_id].remove(websocket)
            if not self.active_connections[table_id]:
                del self.active_connections[table_id]

    async def broadcast_to_all(self, message: str):
        """모든 연결된 클라이언트에게 메시지 전송"""
        for table_connections in self.active_connections.values():
            for connection in table_connections:
                try:
                    await connection.send_text(message)
                except:
                    pass  # 연결이 끊어진 경우 무시

    async def broadcast_to_table(self, table_id: int, message: str):
        """특정 테이블에게만 메시지 전송"""
        if table_id in self.active_connections:
            for connection in self.active_connections[table_id]:
                try:
                    await connection.send_text(message)
                except:
                    pass

    async def broadcast(self, message: str):
        """기존 호환성을 위한 메서드"""
        await self.broadcast_to_all(message)

    def get_online_tables(self) -> List[int]:
        """현재 온라인인 테이블 목록 반환"""
        return list(self.active_connections.keys())

    def set_nickname(self, table_id: int, nickname: str):
        """테이블의 닉네임 설정"""
        self.table_nicknames[table_id] = nickname

    def get_nickname(self, table_id: int) -> str:
        """테이블의 닉네임 반환"""
        return self.table_nicknames.get(table_id, f"테이블{table_id}")

manager = ConnectionManager()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    # 기본 테이블 ID (관리자용)으로 0을 사용
    await manager.connect(websocket, 0)
    try:
        while True:
            data = await websocket.receive_text()
            await manager.broadcast_to_all(f"Message text was: {data}")
    except WebSocketDisconnect:
        manager.disconnect(websocket, 0)

@app.websocket("/ws/{table_id}")
async def websocket_chat_endpoint(websocket: WebSocket, table_id: int):
    await manager.connect(websocket, table_id)
    try:
        while True:
            data = await websocket.receive_text()
            # 클라이언트에서 ping 메시지 처리
            if data == "ping":
                await websocket.send_text("pong")
            else:
                # 다른 메시지 처리 (필요시 확장)
                pass
    except WebSocketDisconnect:
        manager.disconnect(websocket, table_id)

@app.post("/update_payment_status")
async def update_payment_status(
    request: Request,
    db: Session = Depends(get_db)
):
    try:
        data = await request.json()
        table_id = data.get('table_id')
        status = data.get('status')
        
        if not table_id or not status:
            return {"success": False, "error": "Missing required fields"}
            
        # Get the latest order for this table
        order = db.query(Order).filter(
            Order.table_id == table_id
        ).order_by(Order.created_at.desc()).first()
        
        if not order:
            return {"success": False, "error": "Order not found"}
            
        order.payment_status = status
        db.commit()
        
        return {"success": True}
    except Exception as e:
        db.rollback()
        return {"success": False, "error": str(e)}

@app.get("/api/menu-data")
async def get_menu_data_api(db: Session = Depends(get_db)):
    """채팅 주문용 메뉴 데이터 API"""
    try:
        menu_item_details_for_js, menu_names_by_id, menu_items_grouped_by_category, category_display_names = get_menu_data(db)
        return {
            "menu_items": menu_item_details_for_js,
            "menu_names": menu_names_by_id,
            "categories": category_display_names
        }
    except Exception as e:
        print(f"Error in get_menu_data_api: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to load menu data")

@app.post("/chat/gift-order")
async def create_gift_order(
    request: GiftOrderRequest,
    db: Session = Depends(get_db)
):
    """다른 테이블에 주문하기 (선물 주문)"""
    try:
        print(f"Received gift order - from: {request.from_table_id}, to: {request.to_table_id}, menu: {request.menu}")
        
        # 메뉴 데이터 가져오기
        menu_item_details_for_js, menu_names_by_id, menu_items_grouped_by_category, category_display_names = get_menu_data(db)
        
        # 주문 금액 계산 및 메뉴 유효성 검사
        total_amount = 0
        valid_order_items = {}
        
        for item_id, quantity in request.menu.items():
            try:
                quantity = int(quantity)
                if quantity <= 0:
                    continue
                    
                item = menu_item_details_for_js.get(str(item_id))
                if not item or not item['is_active']:
                    continue
                
                item_total = item['price'] * quantity
                total_amount += item_total
                valid_order_items[item_id] = quantity
                
            except (ValueError, TypeError) as e:
                print(f"Error processing item {item_id}: {str(e)}")
                continue
        
        if not valid_order_items:
            raise HTTPException(status_code=400, detail="No valid items in order")
        
        # 주문 생성
        order = Order(
            table_id=request.to_table_id,  # 받는 테이블
            menu=valid_order_items,
            amount=total_amount,
            payment_status="confirmed"  # 선물 주문은 바로 결제 확인됨
        )
        order.confirmed_at = datetime.utcnow()
        
        db.add(order)
        db.commit()
        db.refresh(order)
        
        # 선물한 사람 정보
        from_nickname = manager.get_nickname(request.from_table_id)
        to_nickname = manager.get_nickname(request.to_table_id)
        
        # WebSocket으로 받는 테이블에 알림
        gift_notification = {
            "type": "gift_order",
            "order_id": order.id,
            "from_table_id": request.from_table_id,
            "from_nickname": from_nickname,
            "to_table_id": request.to_table_id,
            "amount": total_amount,
            "menu_items": [
                f"{menu_names_by_id.get(item_id, '알 수 없는 메뉴')} x {quantity}"
                for item_id, quantity in valid_order_items.items()
            ],
            "message": request.message
        }
        
        # 받는 테이블에 알림
        await manager.broadcast_to_table(request.to_table_id, json.dumps(gift_notification))
        
        # 전체 채팅에도 알림 (선택적)
        chat_notification = {
            "type": "gift_announcement",
            "from_nickname": from_nickname,
            "to_nickname": to_nickname,
            "amount": total_amount
        }
        await manager.broadcast_to_all(json.dumps(chat_notification))
        
        # 관리자/주방에도 알림
        admin_notification = {
            "type": "new_order",
            "order_id": order.id,
            "table_id": request.to_table_id,
            "amount": total_amount,
            "is_gift": True,
            "from_table_id": request.from_table_id
        }
        await manager.broadcast_to_table(0, json.dumps(admin_notification))  # 관리자 테이블
        
        return {
            "success": True,
            "order_id": order.id,
            "message": f"{from_nickname}님이 {to_nickname}님에게 주문을 선물했습니다!"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Unexpected error in create_gift_order: {str(e)}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Internal server error")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000) 