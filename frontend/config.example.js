// 배포 시 GitHub Actions가 CloudFormation 출력값으로 config.js를 자동 생성합니다.
// 로컬에서 확인하려면 이 파일을 config.js로 복사해 값을 채우세요.
window.APP_CONFIG = {
  apiUrl: "https://xxxx.execute-api.ap-northeast-2.amazonaws.com",
  cognitoDomain: "https://invest-desk-xxxx.auth.ap-northeast-2.amazoncognito.com",
  clientId: "xxxxxxxxxxxxxxxxxxxxxxxxxx",
  // 로그인 없이 화면만 보려면 true (샘플 데이터 사용, API 호출 안 함)
  demo: false,
};
