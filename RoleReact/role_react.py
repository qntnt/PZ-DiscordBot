import re
import discord
from typing import Tuple, Dict, Union, List
from discord.ext.commands import Converter, RoleConverter
from redbot.core import commands, Config, checks
from redbot.core.commands import Context
from redbot.core.utils.common_filters import filter_mass_mentions, filter_urls, filter_various_mentions, normalize_smartquotes
from redbot.core.utils.chat_formatting import humanize_list, escape
from redbot.core.utils.menus import menu, start_adding_reactions
from redbot.core.utils.predicates import ReactionPredicate
from datetime import datetime
import functools


def compose(*functions):
    return functools.reduce(lambda f, g: lambda x: f(g(x)), functions, lambda x: x)


def sanitize_input(input: str):
    fn = compose(
        filter_mass_mentions,
        filter_urls,
        filter_various_mentions,
        normalize_smartquotes,
    )
    return escape(fn(input))


class RoleHierarchyConverter(commands.RoleConverter):
    async def convert(self, ctx: commands.Context, argument: str) -> discord.Role:
        if not ctx.me.guild_permissions.manage_roles:
            raise commands.BadArgument(
                "I require manage roles permission to use this command.")
        try:
            role = await commands.RoleConverter().convert(ctx, argument)
        except commands.BadArgument:
            raise
        if ctx.author.id == ctx.guild.owner.id:
            return role
        else:
            if role >= ctx.me.top_role:
                raise commands.BadArgument(
                    "That role is higher than my highest role in the discord hierarchy.")
            if role.position >= ctx.author.top_role.position:
                raise commands.BadArgument(
                    "That role is higher than your own in the discord hierarchy.")
        return role


class RoleEmojiConverter(Converter):
    async def convert(self, ctx: Context, argument: str) -> Tuple[discord.Role, str]:
        arg_split = re.split(r";|,|\||-", argument)
        try:
            role, emoji = arg_split
        except Exception:
            raise commands.BadArgument(
                "Role Emoji must be a role followed by an "
                "emoji separated by either `;`, `,`, `|`, or `-`."
            )
        custom_emoji = None
        try:
            custom_emoji = await commands.PartialEmojiConverter().convert(ctx, emoji.strip())
        except commands.BadArgument:
            pass

        if not custom_emoji:
            try:
                await ctx.message.add_reaction(str(emoji.strip()))
                custom_emoji = emoji
            except discord.errors.HTTPException:
                raise commands.BadArgument(
                    "That does not look like a valid emoji.")

        try:
            # TODO role = await RoleHierarchyConverter().convert(ctx, role.strip())
            role = await RoleConverter().convert(ctx, role.strip())
        except commands.BadArgument:
            raise
        return role, custom_emoji


class RoleCategoryConverter(Converter):
    async def convert(self, ctx: Context, argument: str) -> Tuple[str, discord.Role, str]:
        arg_split = re.split(r";|,|\||-", argument)
        try:
            role, category = arg_split
        except Exception:
            raise commands.BadArgument(
                "Category Role must be a role followed by a category separated by either `;`, `,`, `|`, or `-`."
            )

        category = sanitize_input(category)

        try:
            # TODO role = await RoleHierarchyConverter().convert(ctx, role.strip())
            role = await RoleConverter().convert(ctx, role.strip())
        except commands.BadArgument:
            raise
        return role, category


class RoleReact(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(
            self, identifier=28495814093949, force_registration=True)
        default_global = {
            'version': '0.0.0',
        }
        default_guild = {
            'reaction_message_ref': {},
            'roles': {},
            'categories': {
                '': {
                    'roles': {},
                },
            },
        }
        default_role = {}
        default_member = {}
        self.config.register_global(**default_global)
        self.config.register_guild(**default_guild)
        self.config.register_role(**default_role)
        self.config.register_member(**default_member)

    def get_guild_config(self, ctx: Context):
        return self.config.guild(ctx.guild)

    @commands.group()
    async def roles(self, ctx: Context):
        """
        Role reaction commands.
        """
        pass

    # TODO Remove this
    @roles.command(name='debugcreate')
    async def debugaddrole(self, ctx: Context, *role_names: str):
        for role_name in role_names:
            role = await ctx.guild.create_role(name=role_name)
        await ctx.send('Created {}'.format(humanize_list(role_names)))

    # TODO Remove this
    @roles.command(name='debugremove')
    async def debugremoverole(self, ctx: Context, *roles: RoleConverter):
        for role in roles:
            await role.delete()
        await ctx.send('Removed {}'.format(humanize_list(roles)))

    @roles.command(name='add')
    # TODO @commands.admin_or_permissions(manage_roles=True)
    async def add_roles(self, ctx: Context, *role_emoji: RoleEmojiConverter):
        async with self.get_guild_config(ctx).roles() as roles:
            for role, emoji in role_emoji:
                roles[role.name] = {
                    'emoji': emoji,
                }
        # Add to blank category
        async with self.get_guild_config(ctx).categories() as categories:
            for role, emoji in role_emoji:
                categories['']['roles'][role.name] = True
        await ctx.send('Added {}'.format(humanize_list([role.name for role, emoji in role_emoji])))

    @roles.command(name='print')
    # TODO @commands.admin_or_permissions(manage_roles=True)
    async def print_roles(self, ctx: Context):
        async with self.get_guild_config(ctx).roles() as all_roles:
            msg = ''
            for role in sorted(all_roles):
                msg += '> {} - {}\n'.format(all_roles[role]['emoji'], role)
            if msg == '':
                msg = 'No roles configured'
            await ctx.send(msg)

    @roles.command(name='remove')
    # TODO @commands.admin_or_permissions(manage_roles=True)
    async def remove_roles(self, ctx: Context, *roles_to_remove: RoleConverter):
        async with self.get_guild_config(ctx).roles() as roles:
            for role in list(roles_to_remove):
                try:
                    roles.pop(role.name)
                except KeyError:
                    pass

        async with self.get_guild_config(ctx).categories() as categories:
            for category_name in list(categories):
                for role in list(roles_to_remove):
                    try:
                        categories[category_name]['roles'].pop(role.name)
                    except KeyError:
                        pass
                try:
                    if category_name != '' and len(categories[category_name]['roles']) == 0:
                        categories.pop(category_name)
                except KeyError:
                    pass
        await ctx.send('Removed {}'.format(humanize_list(roles_to_remove)))

    @roles.command(name='setmenu')
    # TODO @commands.admin_or_permissions(manage_roles=True)
    async def setmenu_roles(self, ctx: Context, message: discord.Message):
        async with self.get_guild_config(ctx).reaction_message_ref() as reaction_message_ref:
            reaction_message_ref['message_id'] = message.id
            reaction_message_ref['channel_id'] = message.channel.id
            async with self.get_guild_config(ctx).roles() as roles:
                for role in roles:
                    await message.add_reaction(roles[role]['emoji'])
            await ctx.send('Set role reaction menu message: {}\n> To link to it, use the command `roles link`.'.format(message.jump_url))

    @roles.command(name='unsetmenu')
    # TODO @commands.admin_or_permissions(manage_roles=True)
    async def unsetmenu_roles(self, ctx: Context):
        async with self.get_guild_config(ctx).reaction_message_ref() as reaction_message_ref:
            reaction_message_ref = {}
        await ctx.send('Menu message unset')

    @roles.group(name='link')
    async def link_roles(self, ctx: Context):
        """
        Link to the role reaction message
        """
        async with self.get_guild_config(ctx).reaction_message_ref() as reaction_message_ref:
            url = 'https://discord.com/channels/{}/{}/{}'.format(
                ctx.guild.id,
                reaction_message_ref['channel_id'],
                reaction_message_ref['message_id'],
            )
            await ctx.send('Self-assign roles here: {}'.format(url))

    @commands.group()
    async def categories(self, ctx: Context):
        """
        Role reaction categories commands.
        """
        pass

    @categories.command()
    # TODO @commands.admin_or_permissions(manage_roles=True)
    async def assign(self, ctx: Context, *role_categories: RoleCategoryConverter):
        msg = ''
        async with self.get_guild_config(ctx).categories() as categories:
            # Remove old categories
            for category_name in list(categories):
                for role, _ in role_categories:
                    try:
                        removed = categories[category_name]['roles'].pop(
                            role.name)
                        if removed and category_name != '':
                            msg += '> - Removed `{}` (category) from `{}` (role)\n'.format(
                                category_name, role.name)
                    except KeyError:
                        pass

            # Clean up empty categories
            for category_name in list(categories):
                if len(categories[category_name]['roles']) == 0:
                    try:
                        categories.pop(category_name)
                    except KeyError:
                        pass

            # Add new categories
            for role, category_name in role_categories:
                try:
                    category = categories[category_name]
                except KeyError:
                    category = {
                        'roles': {},
                    }
                category['roles'][role.name] = True
                categories[category_name] = category
                if category_name != '':
                    msg += '> + Added `{}` (category) to `{}` (role)\n'.format(
                        category_name, role.name)
        await ctx.send(msg)

    @categories.command()
    # TODO @commands.admin_or_permissions(manage_roles=True)
    async def unassign(self, ctx: Context, *roles: RoleConverter):
        async with self.get_guild_config(ctx).categories() as categories:
            for category_name in list(categories):
                # Remove role from categories that have it
                for role in roles:
                    if category_name != '':
                        try:
                            removed = categories[category_name]['roles'].pop(
                                role.name)
                        except KeyError:
                            pass
                    # Add to blank category
                    categories['']['roles'][role.name] = True
                # Clean up empty categories
                if category_name != '' and len(categories[category_name]['roles']) == 0:
                    try:
                        categories.pop(category_name)
                    except KeyError:
                        pass
        role_text = humanize_list(['`{}`'.format(role.name) for role in roles])
        await ctx.send('Removed all categories from roles {}'.format(role_text))

    @categories.command(name='print')
    # TODO @commands.admin_or_permissions(manage_roles=True)
    async def print_categories(self, ctx: Context):
        async with self.get_guild_config(ctx).categories() as categories:
            async with self.get_guild_config(ctx).roles() as roles:
                msg = ''
                for category_name in sorted(list(categories)):
                    if category_name != '':
                        msg += '> \n> **{}**\n'.format(category_name)
                    else:
                        msg += '> \n> **Uncategorized**\n'
                    for role in categories[category_name]['roles']:
                        try:
                            emoji = roles[role]['emoji']
                            msg += '> {} - {}\n'.format(
                                roles[role]['emoji'], role)
                        except KeyError:
                            msg += '> {} (no reaction set)\n'.format(role)
                if msg == '':
                    msg = 'There are no categories configured'
                await ctx.send(msg)

    @categories.command(name='remove')
    # TODO @commands.admin_or_permissions(manage_roles=True)
    async def remove_categories(self, ctx: Context, *category_names: str):
        async with self.get_guild_config(ctx).categories() as categories:
            for category_name in category_names:
                try:
                    categories.pop(category_name)
                except KeyError:
                    pass
            await ctx.send('Removed {}'.format(humanize_list(category_names)))

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if payload.guild_id is None or payload.user_id == self.bot.user.id:
            return
        guild_config = self.config.guild_from_id(payload.guild_id)
        async with guild_config.reaction_message_ref() as reaction_message_ref:
            if not reaction_message_ref['channel_id'] or not reaction_message_ref['message_id']:
                return
            if payload.channel_id != reaction_message_ref['channel_id'] or payload.message_id != reaction_message_ref['message_id']:
                return

        async with guild_config.roles() as roles:
            for role_name in roles:
                role_emoji = roles[role_name]['emoji']
                if str(payload.emoji) == str(role_emoji):
                    user_id = payload.user_id
                    channel = self.bot.get_channel(payload.channel_id)
                    member = channel.guild.get_member(payload.user_id)
                    message = await channel.fetch_message(payload.message_id)
                    ctx = await self.bot.get_context(message)
                    role = await RoleConverter().convert(ctx, role_name)
                    await member.add_roles(role)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        if payload.guild_id is None or payload.user_id == self.bot.user.id:
            return
        guild_config = self.config.guild_from_id(payload.guild_id)

        async with guild_config.reaction_message_ref() as reaction_message_ref:
            if not reaction_message_ref['channel_id'] or not reaction_message_ref['message_id']:
                return
            if payload.channel_id != reaction_message_ref['channel_id'] or payload.message_id != reaction_message_ref['message_id']:
                return

        async with guild_config.roles() as roles:
            for role_name in roles:
                role_emoji = roles[role_name]['emoji']
                if str(payload.emoji) == str(role_emoji):
                    user_id = payload.user_id
                    channel = self.bot.get_channel(payload.channel_id)
                    member = channel.guild.get_member(payload.user_id)
                    message = await channel.fetch_message(payload.message_id)
                    ctx = await self.bot.get_context(message)
                    role = await RoleConverter().convert(ctx, role_name)
                    await member.remove_roles(role)
