from typing import Dict, Type
from app.models.monitor_target import MonitorTarget, ServiceType
from app.services.abstract_site_monitor import AbstractSiteMonitor
from app.services.coupang_site_monitor import CoupangSiteMonitor
from app.services.naver_site_monitor import NaverSiteMonitor

class SiteMonitorFactory:
    """사이트 모니터링 서비스 팩토리"""
    
    _services: Dict[ServiceType, Type[AbstractSiteMonitor]] = {
        ServiceType.COUPANG: CoupangSiteMonitor,
        ServiceType.NAVER: NaverSiteMonitor
    }
    
    @classmethod
    def create_service(cls, target: MonitorTarget) -> AbstractSiteMonitor:
        """
        모니터링 대상의 타입에 따라 적절한 서비스를 생성합니다.
        """
        service_class = cls._services.get(target.service_type)
        if not service_class:
            raise ValueError(f"Unsupported monitor type: {target.service_type}")
            
        return service_class() 