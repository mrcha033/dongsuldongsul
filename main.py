from fastapi import FastAPI, Request, Form, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy import create_engine, Column, Integer, String, DateTime, JSON
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
    created_at = Column(DateTime, default=datetime.utcnow)
    confirmed_at = Column(DateTime, nullable=True)

# 데이터베이스 테이블 생성
Base.metadata.create_all(bind=engine)

# 의존성
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# 메뉴 가격 정보
MENU_PRICES = {
    "beer": 5000,
    "soju": 4000,
    "makgeolli": 6000,
    "dakgalbi": 18000,
    "tteokbokki": 12000,
    "ramen": 8000,
    "fried_chicken": 16000,
    "pajeon": 14000,
    "bibimbap": 10000,
    "kimchi_stew": 9000,
}

# 메뉴 카테고리 정보
MENU_CATEGORIES = {
    "drinks": {
        "name": "음료",
        "items": ["beer", "soju", "makgeolli"]
    },
    "main_dishes": {
        "name": "메인 요리",
        "items": ["dakgalbi", "tteokbokki", "ramen", "fried_chicken"]
    },
    "side_dishes": {
        "name": "사이드 메뉴",
        "items": ["pajeon", "bibimbap", "kimchi_stew"]
    }
}

# 메뉴 한글 이름
MENU_NAMES = {
    "beer": "맥주",
    "soju": "소주",
    "makgeolli": "막걸리",
    "dakgalbi": "닭갈비",
    "tteokbokki": "떡볶이",
    "ramen": "라면",
    "fried_chicken": "치킨",
    "pajeon": "파전",
    "bibimbap": "비빔밥",
    "kimchi_stew": "김치찌개"
}

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
async def order_page(request: Request, table: int):
    return templates.TemplateResponse(
        "order.html",
        {
            "request": request,
            "table_id": table,
            "menu_prices": MENU_PRICES,
            "menu_categories": MENU_CATEGORIES,
            "menu_names": MENU_NAMES
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
    amount = sum(MENU_PRICES[k] * int(v) for k, v in menu_dict.items() if int(v) > 0)
    
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
    confirmed_orders = db.query(Order).filter(
        Order.payment_status == "confirmed"
    ).order_by(Order.confirmed_at.desc()).all()
    
    return templates.TemplateResponse(
        "kitchen.html",
        {
            "request": request,
            "orders": confirmed_orders,
            "username": username
        }
    )

@app.get("/admin/logout")
async def logout():
    """로그아웃 처리"""
    response = RedirectResponse(url="/", status_code=303)
    response.headers["WWW-Authenticate"] = "Basic"
    return response

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000) 