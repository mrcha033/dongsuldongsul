from fastapi import FastAPI, Request, Form, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy import create_engine, Column, Integer, String, DateTime, JSON, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
import json
import os
import qrcode
from io import BytesIO
import base64
import secrets

# FastAPI 앱 생성
app = FastAPI()

# 정적 파일과 템플릿 설정
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# 관리자 인증 설정
security = HTTPBasic()
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "your-secure-password"  # 실제 운영시에는 환경 변수로 관리

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
def init_menu_data(db: SessionLocal):
    """초기 메뉴 데이터 생성"""
    if db.query(MenuItem).first() is None:
        initial_menu = [
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
def get_menu_data(db: SessionLocal):
    """현재 활성화된 메뉴 데이터를 반환"""
    menu_items = db.query(MenuItem).filter(MenuItem.is_active == True).all()
    
    menu_prices = {item.name_en: item.price for item in menu_items}
    menu_names = {item.name_en: item.name_kr for item in menu_items}
    
    # 카테고리별 메뉴 그룹화
    menu_categories = {
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
    
    return menu_prices, menu_names, menu_categories

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
    from io import BytesIO
    
    # 임시 ZIP 파일 생성
    zip_buffer = BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        base_url = request.base_url
        for table_id in range(1, 11):
            order_url = f"{base_url}order?table={table_id}"
            qr_path = generate_qr_code(order_url, table_id)
            zip_file.write(qr_path, f"table_{table_id}_qr.png")
    
    # ZIP 파일 포인터를 처음으로 되돌림
    zip_buffer.seek(0)
    
    return FileResponse(
        zip_buffer,
        media_type="application/zip",
        filename="table_qr_codes.zip"
    )

@app.get("/order", response_class=HTMLResponse)
async def order_page(request: Request, table: int, db: SessionLocal = Depends(get_db)):
    menu_prices, menu_names, menu_categories = get_menu_data(db)
    return templates.TemplateResponse(
        "order.html",
        {
            "request": request,
            "table_id": table,
            "menu_prices": menu_prices,
            "menu_categories": menu_categories,
            "menu_names": menu_names
        }
    )

@app.post("/submit_order")
async def submit_order(
    request: Request,
    table_id: int = Form(...),
    menu: str = Form(...),
    db: SessionLocal = Depends(get_db)
):
    menu_dict = json.loads(menu)
    menu_prices, _, _ = get_menu_data(db)
    amount = sum(menu_prices[k] * int(v) for k, v in menu_dict.items() if int(v) > 0)
    
    order = Order(
        table_id=table_id,
        menu=menu_dict,
        amount=amount,
        payment_status="pending"
    )
    
    db.add(order)
    db.commit()
    db.refresh(order)
    
    return templates.TemplateResponse(
        "order_success.html",
        {
            "request": request,
            "order": order
        }
    )

@app.get("/admin/orders", response_class=HTMLResponse)
async def admin_orders(
    request: Request,
    db: SessionLocal = Depends(get_db),
    username: str = Depends(verify_admin)
):
    pending_orders = db.query(Order).filter(Order.payment_status == "pending").all()
    return templates.TemplateResponse(
        "admin_orders.html",
        {
            "request": request,
            "orders": pending_orders,
            "username": username
        }
    )

@app.post("/admin/orders/confirm/{order_id}")
async def confirm_order(
    order_id: int,
    db: SessionLocal = Depends(get_db),
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
    db: SessionLocal = Depends(get_db),
    username: str = Depends(verify_admin)
):
    cooking_orders = db.query(Order).filter(
        Order.payment_status == "confirmed",
        Order.cooking_status.in_(["pending", "cooking"])
    ).order_by(Order.confirmed_at.desc()).all()
    
    completed_orders = db.query(Order).filter(
        Order.payment_status == "confirmed",
        Order.cooking_status == "completed"
    ).order_by(Order.completed_at.desc()).limit(10).all()
    
    return templates.TemplateResponse(
        "kitchen.html",
        {
            "request": request,
            "cooking_orders": cooking_orders,
            "completed_orders": completed_orders,
            "username": username
        }
    )

@app.post("/kitchen/update-status/{order_id}")
async def update_cooking_status(
    order_id: int,
    status: str = Form(...),
    db: SessionLocal = Depends(get_db),
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
    db: SessionLocal = Depends(get_db),
    username: str = Depends(verify_admin)
):
    """테이블별 주문 내역 조회"""
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
            "username": username
        }
    )

@app.get("/admin/menu", response_class=HTMLResponse)
async def menu_management(
    request: Request,
    db: SessionLocal = Depends(get_db),
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
    db: SessionLocal = Depends(get_db),
    username: str = Depends(verify_admin)
):
    """새 메뉴 추가"""
    try:
        menu_item = MenuItem(
            name_kr=name_kr,
            name_en=name_en,
            price=price,
            category=category
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
    is_active: bool = Form(False),
    db: SessionLocal = Depends(get_db),
    username: str = Depends(verify_admin)
):
    """메뉴 수정"""
    menu_item = db.query(MenuItem).filter(MenuItem.id == item_id).first()
    if not menu_item:
        raise HTTPException(status_code=404, detail="Menu item not found")
    
    try:
        menu_item.name_kr = name_kr
        menu_item.name_en = name_en
        menu_item.price = price
        menu_item.category = category
        menu_item.is_active = is_active
        db.commit()
        return RedirectResponse(url="/admin/menu", status_code=303)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/admin/menu/delete/{item_id}")
async def delete_menu_item(
    item_id: int,
    db: SessionLocal = Depends(get_db),
    username: str = Depends(verify_admin)
):
    """메뉴 삭제 (비활성화)"""
    menu_item = db.query(MenuItem).filter(MenuItem.id == item_id).first()
    if not menu_item:
        raise HTTPException(status_code=404, detail="Menu item not found")
    
    menu_item.is_active = False
    db.commit()
    return RedirectResponse(url="/admin/menu", status_code=303)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000) 