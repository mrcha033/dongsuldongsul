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

# FastAPI 앱 생성
app = FastAPI()

# 정적 파일과 템플릿 설정
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# 커스텀 Jinja2 필터 추가
def format_currency(value):
    """숫자를 통화 형식으로 포맷팅 (예: 1,234,567)"""
    return "{:,}".format(int(value))

templates.env.filters["format_currency"] = format_currency

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
            MenuItem(name_kr="상차림비(인당)", name_en="table", price=6000, category="table"),
            MenuItem(name_kr="맥주", name_en="beer", price=5000, category="drinks"),
            MenuItem(name_kr="소주", name_en="soju", price=4000, category="drinks"),
            MenuItem(name_kr="막걸리", name_en="makgeolli", price=6000, category="drinks"),
            MenuItem(name_kr="닭갈비", name_en="dakgalbi", price=18000, category="main_dishes"),
            MenuItem(name_kr="떡볶이", name_en="tteokbokki", price=12000, category="main_dishes"),
            MenuItem(name_kr="라면", name_en="ramen", price=8000, category="main_dishes"),
            MenuItem(name_kr="치킨", name_en="fried_chicken", price=16000, category="main_dishes"),
            MenuItem(name_kr="파전", name_en="pajeon", price=14000, category="side_dishes"),
            MenuItem(name_kr="비빔밥", name_en="bibimbap", price=10000, category="side_dishes"),
            MenuItem(name_kr="김치찌개", name_en="kimchi_stew", price=9000, category="side_dishes"),
        ]
        db.add_all(initial_menu)
        db.commit()

# 메뉴 데이터 초기화
init_menu_data(next(get_db()))

# 메뉴 관련 함수들
def get_menu_data(db: Session) -> Tuple[Dict[str, int], Dict[str, str], Dict[str, Dict[str, Any]], Dict[str, MenuItem]]:
    """현재 활성화된 메뉴 데이터를 반환"""
    menu_items = db.query(MenuItem).filter(MenuItem.is_active == True).all()
    
    menu_prices = {str(item.id): item.price for item in menu_items}
    menu_names = {str(item.id): item.name_kr for item in menu_items}
    
    # 카테고리별 메뉴 그룹화
    menu_categories = {
        "table": {
            "name": "상차림비(인당)",
            "items": [item.name_en for item in menu_items if item.category == "table"]
        },
        "drinks": {
            "name": "음료",
            "items": [item.name_en for item in menu_items if item.category == "drinks"]
        },
        "main_dishes": {
            "name": "메인 요리",
            "items": [item.name_en for item in menu_items if item.category == "main_dishes"]
        },
        "side_dishes": {
            "name": "사이드 메뉴",
            "items": [item.name_en for item in menu_items if item.category == "side_dishes"]
        }
    }
    
    # id를 키로 사용하는 메뉴 아이템 딕셔너리 생성
    return menu_prices, menu_names, menu_categories, {str(item.id): item for item in menu_items}

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
    # 메뉴 아이템 조회
    menu_items = {}
    for category in ["drinks", "main_dishes", "side_dishes"]:
        items = db.query(MenuItem).filter(MenuItem.category == category).all()
        menu_items[category] = [{
            "id": item.id,
            "name_kr": item.name_kr,
            "name_en": item.name_en,
            "price": item.price,
            "description": item.description,
            "image_filename": item.image_filename
        } for item in items]
    
    # 상차림비 추가
    table_charge = db.query(MenuItem).filter(MenuItem.category == "table").first()
    if table_charge:
        menu_items["table"] = [{
            "id": table_charge.id,
            "name_kr": table_charge.name_kr,
            "name_en": table_charge.name_en,
            "price": table_charge.price,
            "description": table_charge.description,
            "image_filename": table_charge.image_filename
        }]
    
    return templates.TemplateResponse(
        "order.html",
        {"request": request, "table_id": table, "menu_items": menu_items}
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
            menu_prices, menu_names, menu_categories, menu_items = get_menu_data(db)
            print(f"Retrieved menu data - prices: {menu_prices}, names: {menu_names}")
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
                item = menu_items.get(str(item_id))
                if not item:
                    print(f"Warning: Menu item not found for ID {item_id}")
                    continue
                    
                if not item.is_active:
                    print(f"Warning: Menu item {item_id} is not active")
                    continue
                
                item_total = item.price * quantity
                total_amount += item_total
                valid_order_items[item_id] = quantity
                print(f"Added item {item_id}: {quantity} x {item.price} = {item_total}")
                
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
                "menu_names": menu_names
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
    menu_prices, menu_names, menu_categories, menu_items = get_menu_data(db)
    
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
            "menu_names": menu_names
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
    menu_prices, menu_names, menu_categories, menu_items = get_menu_data(db)
    
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
            "menu_names": menu_names
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
    menu_prices, menu_names, menu_categories, menu_items = get_menu_data(db)
    
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
            "menu_names": menu_names  # 메뉴 이름 정보 추가
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
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            await connection.send_text(message)

manager = ConnectionManager()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            await manager.broadcast(f"Message text was: {data}")
    except WebSocketDisconnect:
        manager.disconnect(websocket)

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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000) 