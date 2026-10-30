package com.pycompose.ir

import com.pycompose.ir.generated.IrContract
import com.pycompose.program.Contract

/** The catalog's limits and vocabulary for the expressions a snapshot carries. */
val EXPRESSIONS: Contract =
    Contract(
        depth = IrContract.EXPRESSION_DEPTH,
        nodes = IrContract.EXPRESSION_NODES,
        operations = IrContract.expressionOps,
        streamNames = IrContract.streamNames,
    )
