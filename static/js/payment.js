// 주문 정보를 전역 변수로 저장
const orderInfo = {
    amount: window.orderAmount,
    tableId: window.tableId
};

// 기기 감지 및 UI 분기
function detectDevice() {
    const isAndroid = /Android/i.test(navigator.userAgent);
    
    if (isAndroid) {
        document.getElementById('android-payment').style.display = 'block';
    } else {
        document.getElementById('android-payment').style.display = 'none';
    }
}

// 토스 앱 송금 요청
function requestTossPay() {
    const button = document.getElementById('toss-button');
    const amount = button.dataset.amount;
    const tableId = button.dataset.tableId;
    const phone = "01012345678"; // 토스 등록된 본인 번호
    const message = `테이블${tableId}`;
    const intentUrl = `intent://pay?recipient=${phone}&amount=${amount}&message=${encodeURIComponent(message)}#Intent;scheme=tosspay;package=viva.republica.toss;end`;
    window.location.href = intentUrl;
}

// 계좌번호 복사
function copyAccount() {
    const accountNumber = document.getElementById('account-number').textContent;
    navigator.clipboard.writeText(accountNumber).then(() => {
        alert('계좌번호가 복사되었습니다. 토스 앱에서 송금해주세요!');
    }).catch(err => {
        console.error('계좌번호 복사 실패:', err);
        alert('계좌번호 복사에 실패했습니다. 직접 입력해주세요.');
    });
}

// 페이지 로드 시 이벤트 리스너 등록
document.addEventListener('DOMContentLoaded', () => {
    detectDevice();
    document.getElementById('toss-button').addEventListener('click', requestTossPay);
}); 