// 메뉴 데이터 초기화
const menuDataElement = document.getElementById('menu-data');
const menuItems = JSON.parse(menuDataElement.dataset.menu);
const tableId = document.getElementById('table-data').dataset.tableId;

let orderItems = {};

function updateQuantity(itemId, change) {
    const input = document.getElementById(`quantity-${itemId}`);
    const currentValue = parseInt(input.value);
    const newValue = Math.max(0, currentValue + change);
    
    input.value = newValue;
    
    if (newValue > 0) {
        orderItems[itemId] = newValue;
    } else {
        delete orderItems[itemId];
    }
    
    updateOrderSummary();
}

function updateOrderSummary() {
    const summary = document.getElementById('order-summary');
    const totalAmount = document.getElementById('total-amount');
    const submitButton = document.getElementById('submit-order-btn');
    let total = 0;
    
    summary.innerHTML = '';
    
    for (const [itemId, quantity] of Object.entries(orderItems)) {
        const item = menuItems[itemId];
        if (!item) continue;
        
        const itemTotal = item.price * quantity;
        total += itemTotal;
        
        const itemElement = document.createElement('div');
        itemElement.className = 'order-summary-item';
        itemElement.innerHTML = `
            <div class="d-flex justify-content-between align-items-center">
                <div>
                    <h6 class="mb-0">${item.name_kr}</h6>
                    <small class="text-muted">${item.name_en}</small>
                </div>
                <div class="text-end">
                    <div>${quantity}개</div>
                    <div class="text-primary">${itemTotal.toLocaleString()}원</div>
                </div>
            </div>
        `;
        summary.appendChild(itemElement);
    }
    
    totalAmount.textContent = `${total.toLocaleString()}원`;
    submitButton.disabled = total === 0;
}

async function submitOrder() {
    const submitButton = document.getElementById('submit-order-btn');
    submitButton.disabled = true;
    submitButton.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>주문 처리 중...';
    
    try {
        const response = await fetch('/submit_order', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded'
            },
            body: new URLSearchParams({
                'table_id': tableId,
                'menu': JSON.stringify(orderItems)
            })
        });
        
        if (response.ok) {
            const result = await response.text();
            document.open();
            document.write(result);
            document.close();
        } else {
            throw new Error('주문 처리 중 오류가 발생했습니다.');
        }
    } catch (error) {
        alert(error.message);
        submitButton.disabled = false;
        submitButton.innerHTML = '<i class="bi bi-check-circle me-2"></i>주문하기';
    }
} 