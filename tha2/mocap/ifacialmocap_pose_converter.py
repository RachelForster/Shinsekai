from abc import ABC, abstractmethod
from typing import Dict, List


class IFacialMocapPoseConverter(ABC):
    @abstractmethod
    def convert(self, ifacialmocap_pose: Dict[str, float]) -> List[float]:
        pass