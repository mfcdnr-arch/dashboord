import { SetMetadata } from '@nestjs/common';

export const PERMISSION_KEY = 'required_permission';
export const SECURABLE_PARAM_KEY = 'securable_param';

/**
 * Отметить метод контроллера требуемый permission-code.
 * @param permissionCode например 'widget.view', 'dashboard.publish'
 * @param securableParam имя route-параметра, в котором лежит securableId (по умолчанию 'id')
 */
export const RequirePermission = (permissionCode: string, securableParam = 'id') =>
    SetMetadata(PERMISSION_KEY, { permissionCode, securableParam });
