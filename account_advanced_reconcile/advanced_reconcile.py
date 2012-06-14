# -*- coding: utf-8 -*-
##############################################################################
#
#    Author: Guewen Baconnier
#    Copyright 2012 Camptocamp SA
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################

from itertools import groupby, product
from operator import itemgetter
from openerp.osv.orm import Model, AbstractModel, TransientModel
from openerp.osv import fields


class account_easy_reconcile_method(Model):

    _inherit = 'account.easy.reconcile.method'

    def _get_all_rec_method(self, cr, uid, context=None):
        methods = super(account_easy_reconcile_method, self).\
            _get_all_rec_method(cr, uid, context=context)
        methods += [
            ('easy.reconcile.advanced.ref',
            'Advanced method, payment ref matches with ref or name'),
            ('easy.reconcile.advanced.tid',
            'Advanced method, payment Transaction ID matches with ref or name')
        ]
        return methods


class easy_reconcile_advanced(AbstractModel):

    _name = 'easy.reconcile.advanced'
    _inherit = 'easy.reconcile.base'

    def _query_moves(self, cr, uid, rec, context=None):
        """Select all move (debit>0) as candidate. Optional choice on invoice
        will filter with an inner join on the related moves.
        """
        select = self._select(rec)
        sql_from = self._from(rec)
        where, params = self._where(rec)
        where += " AND account_move_line.debit > 0 "

        where2, params2 = self._get_filter(cr, uid, rec, context=context)

        if context.get('invoice_ids'):
            # select only move lines with an invoice
            sql_from += (
                " INNER JOIN account_move "
                " ON account_move.id = account_move_line.move_id "
                " INNER JOIN account_invoice "
                " ON account_invoice.move_id = account_move.id ")
            where += " account_invoice.id in (%s) "
            params += tuple(context['invoice_ids'])

        if context.get('partner_ids'):
            where += " AND account_move_line.partner_id IN %s "
            params += tuple(context['partner_ids'])

        query = ' '.join((select, sql_from, where, where2))

        cr.execute(query, params + params2)
        return cr.dictfetchall()

    def _query_payments(self, cr, uid, rec, context=None):
        """Select all move (credit>0) as candidate. Optional choice on invoice
        will filter with an inner join on the related moves.
        """
        select = self._select(rec)
        sql_from = self._from(rec)
        where, params = self._where(rec)
        where += " AND account_move_line.credit > 0 "

        where2, params2 = self._get_filter(cr, uid, rec, context=context)

        if context.get('partner_ids'):
            where += " AND account_move_line.partner_id IN %s "
            params += tuple(context['partner_ids'])

        query = ' '.join((select, sql_from, where, where2))

        cr.execute(query, params + params2)
        return cr.dictfetchall()

    def _matchers(self, cr, uid, rec, move_line, context=None):
        """
        Return the values used as matchers to found the opposite lines

        All the matcher keys in the dict must have their equivalent in
        the `_opposite_matchers`.

        The values of each matcher key will be searched in the
        one returned by the `_opposite_matchers`

        Must be inherited to implement the matchers for one method

        As instance, it can returns:
        return ('ref', move_line['rec'])

        or
        return (('partner_id', move_line['partner_id']),
                ('ref', "prefix_%s" % move_line['rec']))

        All the matchers have to be found in the opposite lines
        to consider them as "opposite"

        The matchers will be evaluated in the same order than declared
        vs the the opposite matchers, so you can gain performance by
        declaring first the partners with the less computation.

        All matchers should match with their opposite to be considered
        as "matching".
        So with the previous example, partner_id and ref have to be
        equals on the opposite line matchers.

        :return: tuple of tuples (key, value) where the keys are
            the matchers keys
            (must be the same than `_opposite_matchers` returns,
            and their values to match in the opposite lines.
            A matching key can have multiples values.
        """
        raise NotImplementedError

    def _opposite_matchers(self, cr, uid, rec, move_line, context=None):
        """
        Return the values of the opposite line used as matchers
        so the line is matched

        Must be inherited to implement the matchers for one method
        It can be inherited to apply some formatting of fields
        (strip(), lower() and so on)

        This method is the counterpart of the `_matchers()` method.

        Each matcher have to yield its value respecting the orders
        of the `_matchers()`.

        When a matcher does not correspond, the next matchers won't
        be evaluated so the ones which need the less computation
        have to be executed first.

        If the `_matchers()` returns:
        (('partner_id', move_line['partner_id']),
         ('ref', move_line['ref']))

        Here, you should yield :
        yield ('partner_id', move_line['partner_id'])
        yield ('ref', move_line['ref'])

        Note that a matcher can contain multiple values, as instance,
        if for a move line, you want to search from its `ref` in the
        `ref` or `name` fields of the opposite move lines, you have to
        yield ('partner_id', move_line['partner_id'])
        yield ('ref', (move_line['ref'], move_line['name'])

        An OR is used between the values for the same key.
        An AND is used between the differents keys.

        :param dict move_line: values of the move_line
        :yield: matchers as tuple ('matcher key', value(s))
        """
        raise NotImplementedError

    @staticmethod
    def _compare_values(key, value, opposite_value):
        """Can be inherited to modify the equality condition
        specifically according to the matcher key (maybe using
        a like on 'ref' as instance)
        """
        # consider that empty vals are not valid matchers
        # it can still be inherited for some special cases
        # where it would be allowed
        if not (value and opposite_value):
            return False

        if value == opposite_value:
            return True
        return False

    @staticmethod
    def _compare_matcher_values(key, values, opposite_values):
        """ Compare every values from a matcher vs an opposite matcher
        and return True if it matches
        """
        for value, ovalue in product(values, opposite_values):
            # we do not need to compare all values, if one matches
            # we are done
            if easy_reconcile_advanced._compare_values(key, value, ovalue):
                return True
        return False

    @staticmethod
    def _compare_matchers(matcher, opposite_matcher):
        """
        Prepare and check the matchers to compare
        """
        mkey, mvalue = matcher
        omkey, omvalue = opposite_matcher
        assert mkey == omkey, "A matcher %s is compared with a matcher %s, " \
                " the _matchers and _opposite_matchers are probably wrong" % \
                (mkey, omkey)
        if not isinstance(mvalue, (list, tuple)):
            mvalue = mvalue,
        if not isinstance(omvalue, (list, tuple)):
            omvalue = omvalue,
        return easy_reconcile_advanced._compare_matcher_values(mkey, mvalue, omvalue)

    def _compare_opposite(self, cr, uid, rec, move_line, opposite_move_line,
            matchers, context=None):
        opp_matchers = self._opposite_matchers(cr, uid, rec, opposite_move_line,
                context=context)
        for matcher in matchers:
            try:
                opp_matcher = opp_matchers.next()
            except StopIteration:
                # if you fall here, you probably missed to put a `yield`
                # in `_opposite_matchers()`
                raise ValueError("Missing _opposite_matcher: %s" % matcher[0])

            if not self._compare_matchers(matcher, opp_matcher):
                # if any of the matcher fails, the opposite line
                # is not a valid counterpart
                # directly returns so the next yield of _opposite_matchers
                # are not evaluated
                return False
        return True

    def _search_opposites(self, cr, uid, rec, move_line, opposite_move_lines, context=None):
        """
        Search the opposite move lines for a move line

        :param dict move_line: the move line for which we search opposites
        :param list opposite_move_lines: list of dict of move lines values, the move
            lines we want to search for
        :return: list of matching lines
        """
        matchers = self._matchers(cr, uid, rec, move_line, context=context)
        return [op for op in opposite_move_lines if \
            self._compare_opposite(cr, uid, rec, move_line, op, matchers, context=context)]

    def _action_rec(self, cr, uid, rec, context=None):
        move_lines = self._query_moves(cr, uid, rec, context=context)
        payment_lines = self._query_payments(cr, uid, rec, context=context)
        return self._rec_auto_lines_advanced(
            cr, uid, rec, move_lines, payment_lines, context=context)

    def _skip_line(self, cr, uid, rec, move_line, context=None):
        """
        When True is returned on some conditions, the credit move line
        will be skipped for reconciliation. Can be inherited to
        skip on some conditions. ie: ref or partner_id is empty.
        """
        return False

    def _rec_auto_lines_advanced(self, cr, uid, rec, debit_lines, credit_lines, context=None):
        if context is None:
            context = {}

        reconciled = []
        reconcile_groups = []

        for credit_line in credit_lines:
            opposite_lines = self._search_opposites(
                cr, uid, rec, credit_line, debit_lines, context=context)

            if not opposite_lines:
                continue

            if self._skip_line(cr, uid, rec, credit_line, context=context):
                continue

            opposite_ids = [l['id'] for l in opposite_lines]
            line_ids = opposite_ids + [credit_line['id']]
            for group in reconcile_groups:
                if any([lid in group for lid in opposite_ids]):
                    group.update(line_ids)
                    break
            else:
                reconcile_groups.append(set(line_ids))

        for reconcile_group_ids in reconcile_groups:
            if self._reconcile_lines(cr, uid, reconcile_group_ids,
                    allow_partial=True, context=context):
                reconciled += reconcile_group_ids

        return reconciled


class easy_reconcile_advanced_ref(TransientModel):

    _name = 'easy.reconcile.advanced.ref'
    _inherit = 'easy.reconcile.advanced'
    _auto = True  # False when inherited from AbstractModel

    def _skip_line(self, cr, uid, rec, move_line, context=None):
        """
        When True is returned on some conditions, the credit move line
        will be skipped for reconciliation. Can be inherited to
        skip on some conditions. ie: ref or partner_id is empty.
        """
        return not (move_line.get('ref') and move_line.get('partner_id'))

    def _matchers(self, cr, uid, rec, move_line, context=None):
        """
        Return the values used as matchers to found the opposite lines

        All the matcher keys in the dict must have their equivalent in
        the `_opposite_matchers`.

        The values of each matcher key will be searched in the
        one returned by the `_opposite_matchers`

        Must be inherited to implement the matchers for one method

        As instance, it can returns:
        return ('ref', move_line['rec'])

        or
        return (('partner_id', move_line['partner_id']),
                ('ref', "prefix_%s" % move_line['rec']))

        All the matchers have to be found in the opposite lines
        to consider them as "opposite"

        The matchers will be evaluated in the same order than declared
        vs the the opposite matchers, so you can gain performance by
        declaring first the partners with the less computation.

        All matchers should match with their opposite to be considered
        as "matching".
        So with the previous example, partner_id and ref have to be
        equals on the opposite line matchers.

        :return: tuple of tuples (key, value) where the keys are
            the matchers keys
            (must be the same than `_opposite_matchers` returns,
            and their values to match in the opposite lines.
            A matching key can have multiples values.
        """
        return (('partner_id', move_line['partner_id']),
                ('ref', move_line['ref'].lower().strip()))

    def _opposite_matchers(self, cr, uid, rec, move_line, context=None):
        """
        Return the values of the opposite line used as matchers
        so the line is matched

        Must be inherited to implement the matchers for one method
        It can be inherited to apply some formatting of fields
        (strip(), lower() and so on)

        This method is the counterpart of the `_matchers()` method.

        Each matcher have to yield its value respecting the orders
        of the `_matchers()`.

        When a matcher does not correspond, the next matchers won't
        be evaluated so the ones which need the less computation
        have to be executed first.

        If the `_matchers()` returns:
        (('partner_id', move_line['partner_id']),
         ('ref', move_line['ref']))

        Here, you should yield :
        yield ('partner_id', move_line['partner_id'])
        yield ('ref', move_line['ref'])

        Note that a matcher can contain multiple values, as instance,
        if for a move line, you want to search from its `ref` in the
        `ref` or `name` fields of the opposite move lines, you have to
        yield ('partner_id', move_line['partner_id'])
        yield ('ref', (move_line['ref'], move_line['name'])

        An OR is used between the values for the same key.
        An AND is used between the differents keys.

        :param dict move_line: values of the move_line
        :yield: matchers as tuple ('matcher key', value(s))
        """
        yield ('partner_id', move_line['partner_id'])
        yield ('ref', (move_line['ref'].lower().strip(),
                       move_line['name'].lower().strip()))


class easy_reconcile_advanced_tid(TransientModel):

    # tid means for transaction_id
    _name = 'easy.reconcile.advanced.tid'
    _inherit = 'easy.reconcile.advanced'
    _auto = True  # False when inherited from AbstractModel

    def _skip_line(self, cr, uid, rec, move_line, context=None):
        """
        When True is returned on some conditions, the credit move line
        will be skipped for reconciliation. Can be inherited to
        skip on some conditions. ie: ref or partner_id is empty.
        """
        return not (move_line.get('ref') and move_line.get('partner_id'))

    def _matchers(self, cr, uid, rec, move_line, context=None):
        """
        Return the values used as matchers to found the opposite lines

        All the matcher keys in the dict must have their equivalent in
        the `_opposite_matchers`.

        The values of each matcher key will be searched in the
        one returned by the `_opposite_matchers`

        Must be inherited to implement the matchers for one method

        As instance, it can returns:
        return ('ref', move_line['rec'])

        or
        return (('partner_id', move_line['partner_id']),
                ('ref', "prefix_%s" % move_line['rec']))

        All the matchers have to be found in the opposite lines
        to consider them as "opposite"

        The matchers will be evaluated in the same order than declared
        vs the the opposite matchers, so you can gain performance by
        declaring first the partners with the less computation.

        All matchers should match with their opposite to be considered
        as "matching".
        So with the previous example, partner_id and ref have to be
        equals on the opposite line matchers.

        :return: tuple of tuples (key, value) where the keys are
            the matchers keys
            (must be the same than `_opposite_matchers` returns,
            and their values to match in the opposite lines.
            A matching key can have multiples values.
        """
        return (('partner_id', move_line['partner_id']),
                ('ref', move_line['ref'].lower().strip()))

    def _opposite_matchers(self, cr, uid, rec, move_line, context=None):
        """
        Return the values of the opposite line used as matchers
        so the line is matched

        Must be inherited to implement the matchers for one method
        It can be inherited to apply some formatting of fields
        (strip(), lower() and so on)

        This method is the counterpart of the `_matchers()` method.

        Each matcher have to yield its value respecting the orders
        of the `_matchers()`.

        When a matcher does not correspond, the next matchers won't
        be evaluated so the ones which need the less computation
        have to be executed first.

        If the `_matchers()` returns:
        (('partner_id', move_line['partner_id']),
         ('ref', move_line['ref']))

        Here, you should yield :
        yield ('partner_id', move_line['partner_id'])
        yield ('ref', move_line['ref'])

        Note that a matcher can contain multiple values, as instance,
        if for a move line, you want to search from its `ref` in the
        `ref` or `name` fields of the opposite move lines, you have to
        yield ('partner_id', move_line['partner_id'])
        yield ('ref', (move_line['ref'], move_line['name'])

        An OR is used between the values for the same key.
        An AND is used between the differents keys.

        :param dict move_line: values of the move_line
        :yield: matchers as tuple ('matcher key', value(s))
        """
        yield ('partner_id', move_line['partner_id'])

        prefixes = ('tid_', 'tid_mag_')
        refs = []
        if move_line.get('ref'):
            lref = move_line['ref'].lower().strip()
            refs.append(lref)
            refs += ["%s%s" % (s, lref) for s in prefixes]

        if move_line.get('name'):
            refs.append(move_line['name'].lower().strip())
        yield ('ref', refs)
