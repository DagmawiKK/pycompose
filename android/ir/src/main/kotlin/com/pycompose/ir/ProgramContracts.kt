package com.pycompose.ir

import com.pycompose.ir.generated.IrContract
import com.pycompose.program.Contract
import com.pycompose.program.DrawContract
import com.pycompose.program.FunctionContract
import com.pycompose.program.LayoutContract

/** The catalog's limits and vocabulary for the expressions a snapshot carries. */
val EXPRESSIONS: Contract =
    Contract(
        depth = IrContract.EXPRESSION_DEPTH,
        nodes = IrContract.EXPRESSION_NODES,
        operations = IrContract.expressionOps,
        streamNames = IrContract.streamNames,
    )

/** The catalog's limits and vocabulary for the value functions a snapshot carries. */
val FUNCTIONS: FunctionContract =
    FunctionContract(
        depth = IrContract.FUNCTION_DEPTH,
        nodes = IrContract.FUNCTION_NODES,
        arguments = IrContract.FUNCTION_ARGUMENTS,
        signatures = IrContract.functionSignatures,
    )

/** The catalog's draw calls and limits for the draw programs a snapshot carries. */
val DRAWINGS: DrawContract =
    DrawContract(
        nodes = IrContract.DRAW_NODES,
        draws = IrContract.DRAW_DRAWS,
        repeat = IrContract.DRAW_REPEAT,
        loops = IrContract.DRAW_LOOPS,
        calls = IrContract.drawCalls,
    )

/** The catalog's calls, operations and limits for the layout programs a snapshot carries. */
val LAYOUTS: LayoutContract =
    LayoutContract(
        nodes = IrContract.LAYOUT_NODES,
        repeat = IrContract.LAYOUT_REPEAT,
        loops = IrContract.LAYOUT_LOOPS,
        calls = IrContract.layoutCalls,
        signatures = IrContract.layoutSignatures,
    )
