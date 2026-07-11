import { Body, Controller, Get, Param, Patch, Post } from '@nestjs/common';
import { RequirePermission } from './permission.decorator';
import { AccessControlService } from './access-control.service';

/**
 * Пример использования Guard/Decorator в контроллере виджетов.
 */
@Controller('widgets')
export class WidgetsController {
    constructor(private readonly accessControl: AccessControlService) {}

    @Get(':id')
    @RequirePermission('widget.view', 'id')
    async getWidget(@Param('id') id: string) {
        // Guard уже проверил доступ - здесь только бизнес-логика
        return { id, message: 'данные виджета' };
    }

    @Patch(':id/config')
    @RequirePermission('widget.edit', 'id')
    async updateWidget(@Param('id') id: string, @Body() dto: unknown) {
        return { id, updated: true };
    }

    @Post(':id/access')
    @RequirePermission('widget.edit', 'id')
    async grantWidgetAccess(
        @Param('id') widgetId: string,
        @Body() dto: { subjectType: 'user' | 'role'; subjectId: string; effect: 'allow' | 'deny'; grantedBy: string },
    ) {
        const securableId = await this.accessControl.getSecurableId('widget', widgetId);
        if (!securableId) return { success: false };

        await this.accessControl.grantOrDeny({
            securableId,
            subjectType: dto.subjectType,
            subjectId: dto.subjectId,
            permissionCode: 'widget.view',
            effect: dto.effect,
            grantedBy: dto.grantedBy,
        });

        return { success: true };
    }
}
