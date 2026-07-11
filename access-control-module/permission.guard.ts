import {
    CanActivate,
    ExecutionContext,
    ForbiddenException,
    Injectable,
    UnauthorizedException,
} from '@nestjs/common';
import { Reflector } from '@nestjs/core';
import { AccessControlService, SecurableType } from './access-control.service';
import { PERMISSION_KEY } from './permission.decorator';

interface PermissionMeta {
    permissionCode: string;
    securableParam: string;
}

/**
 * Guard проверяет права доступа к widget/dashboard/folder через fn_resolve_access.
 * Ожидает, что request.user.id заполнен JWT-стратегией аутентификации.
 * Сам определяет object_type по route path (widgets/dashboards/folders).
 */
@Injectable()
export class PermissionGuard implements CanActivate {
    constructor(
        private readonly reflector: Reflector,
        private readonly accessControl: AccessControlService,
    ) {}

    async canActivate(context: ExecutionContext): Promise<boolean> {
        const meta = this.reflector.get<PermissionMeta>(PERMISSION_KEY, context.getHandler());
        if (!meta) {
            return true; // метод не требует проверки доступа
        }

        const request = context.switchToHttp().getRequest();
        const userId: string | undefined = request.user?.id;
        if (!userId) {
            throw new UnauthorizedException('Пользователь не аутентифицирован');
        }

        const objectId = request.params?.[meta.securableParam];
        if (!objectId) {
            throw new ForbiddenException('Не удалось определить объект для проверки доступа');
        }

        const objectType = this.resolveObjectType(meta.permissionCode);
        const securableId = await this.accessControl.getSecurableId(objectType, objectId);
        if (!securableId) {
            throw new ForbiddenException('Объект не найден в системе прав доступа');
        }

        const allowed = await this.accessControl.resolveAccess(userId, securableId, meta.permissionCode);
        if (!allowed) {
            throw new ForbiddenException(`Доступ запрещён: требуется право '${meta.permissionCode}'`);
        }

        return true;
    }

    private resolveObjectType(permissionCode: string): SecurableType {
        if (permissionCode.startsWith('widget.')) return 'widget';
        if (permissionCode.startsWith('dashboard.')) return 'dashboard';
        return 'folder';
    }
}
